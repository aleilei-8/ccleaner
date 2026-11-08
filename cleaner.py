# -*- coding: utf-8 -*-
"""安全清理模块 v3.0

负责执行垃圾文件清理操作，包含完整的安全保护机制：
- 白名单/黑名单校验
- 文件占用检测
- 整目录删除（shutil.rmtree）+ 清理后递归删除空目录（彻底释放空间）
- 大文件保护（>4GB 默认跳过，防误删虚拟机/ISO/备份）
- 权限增强：尝试取所有权后删除
- dry_run 模式、分类清理报告、错误重试
"""

import os
import sys
import logging
import threading
import time
import shutil
import ctypes
import subprocess
from typing import Dict, List, Tuple, Optional, Callable
from dataclasses import dataclass, field

from scanner import ScanCategory
from config import (
    get_protected_directories,
    get_protected_extensions_in_windows,
    get_protected_files,
)
from utils import normalize_path, is_sub_path, is_file_in_use, format_size, empty_recycle_bin, is_process_elevated
from quarantine import Quarantine

logger = logging.getLogger(__name__)


@dataclass
class CleanResult:
    """清理操作的统计结果。"""
    total_files_found: int = 0  # 发现的文件/目录总数
    total_size_found: int = 0  # 发现的总大小
    files_deleted: int = 0  # 成功永久删除的数量（隔离模式关闭时才有）
    size_freed: int = 0  # 释放的空间大小
    files_skipped: int = 0  # 跳过的文件数（受保护/被占用/过大）
    errors: List[str] = field(default_factory=list)  # 错误信息列表
    dry_run: bool = False  # 是否为模拟清理
    by_category: Dict[str, Dict[str, int]] = field(default_factory=dict)  # 每类别统计
    files_quarantined: int = 0  # 隔离（而非永久删除）的数量
    size_quarantined: int = 0  # 隔离释放的空间大小
    quarantine_ids: List[str] = field(default_factory=list)  # 隔离项 id 列表（用于恢复）

    def summary(self) -> str:
        """生成清理结果摘要字符串。"""
        mode = "模拟清理" if self.dry_run else "清理"
        lines = [
            f"{mode}完成！",
            f"  发现: {self.total_files_found} 项 ({format_size(self.total_size_found)})",
            f"  成功{'预估' if self.dry_run else '删除'}: {self.files_deleted} 项 ({format_size(self.size_freed)})",
            f"  跳过的隔离项: {self.files_quarantined} 项 ({format_size(self.size_quarantined)})" if self.files_quarantined else "",
            f"  跳过: {self.files_skipped} 项",
        ]
        lines = [l for l in lines if l]
        if self.errors:
            lines.append(f"  错误数量: {len(self.errors)}")
        return "\n".join(lines)


# 大文件保护阈值（字节）：默认 4GB，超过此大小的单文件/目录默认跳过
LARGE_FILE_THRESHOLD = 4 * 1024 * 1024 * 1024


class Cleaner:
    """安全清理引擎 v3.0。

    在清理前执行多重安全检查，确保不会误删系统关键文件。
    v3.0 重大更新：支持整目录删除、清理后删空目录、大文件保护、权限取所有权。
    """

    MAX_RETRY = 1
    RETRY_DELAY = 1

    def __init__(self, large_file_threshold: int = LARGE_FILE_THRESHOLD,
                 quarantine: Optional[Quarantine] = None):
        """初始化清理器，加载保护规则。

        Args:
            large_file_threshold: 大文件保护阈值（字节），超过则跳过。
            quarantine: 隔离区管理器（可注入，默认新建）。隔离模式开启时删除改移动。
        """
        self._protected_dirs: set = get_protected_directories()
        self._protected_extensions: set = get_protected_extensions_in_windows()
        self._protected_files: set = get_protected_files()
        self._large_file_threshold = large_file_threshold
        self._quarantine = quarantine or Quarantine()
        self._lock = threading.Lock()
        self._is_cleaning: bool = False
        self._progress_callback: Optional[Callable[[int, int, str], None]] = None
        self._cancelled: bool = False

    def set_progress_callback(self, callback: Callable[[int, int, str], None]):
        """设置进度回调函数。"""
        self._progress_callback = callback

    def cancel(self):
        """取消正在进行的清理操作。"""
        self._cancelled = True
        logger.info("清理操作已被用户取消")

    @property
    def is_cleaning(self) -> bool:
        """当前是否正在清理。"""
        return self._is_cleaning

    def _report_progress(self, current: int, total: int, info: str):
        """报告清理进度。"""
        if self._progress_callback:
            try:
                self._progress_callback(current, total, info)
            except Exception as e:
                logger.warning("进度回调异常: %s", e)

    # ======================== 安全保护 ========================

    def _is_protected(self, file_path: str) -> bool:
        """检查文件是否受保护。"""
        norm_path = normalize_path(file_path)

        if norm_path in self._protected_files:
            logger.debug("文件在系统关键文件保护列表中: %s", file_path)
            return True

        for protected_dir in self._protected_dirs:
            if is_sub_path(file_path, protected_dir):
                logger.debug("文件位于受保护目录中: %s (在 %s 下)", file_path, protected_dir)
                return True

        norm_lower = normalize_path(file_path)
        if norm_lower.startswith(normalize_path(r"C:\Windows")):
            ext = os.path.splitext(file_path)[1].lower()
            if ext in self._protected_extensions:
                logger.debug("文件在 Windows 目录下且为受保护扩展名: %s (%s)", file_path, ext)
                return True

        return False

    def _is_large(self, path: str) -> bool:
        """检查路径是否超过大文件保护阈值（防误删 ISO/虚拟机/备份）。"""
        try:
            if os.path.isfile(path):
                return os.path.getsize(path) > self._large_file_threshold
            elif os.path.isdir(path):
                # 目录不在此处判断（整目录清理时已确认是垃圾目录，不按大小卡）
                return False
        except OSError:
            return False
        return False

    # ======================== 权限取所有权（Windows） ========================

    def _take_ownership(self, path: str) -> bool:
        """尝试获取文件/目录的所有权（需要管理员权限）。

        Args:
            path: 文件或目录路径。

        Returns:
            True 表示成功或无需获取（非 Windows/已可访问）。
        """
        if sys.platform != "win32":
            return True
        try:
            # 使用 icacls 获取所有权
            import subprocess
            subprocess.run(
                ["icacls", path, "/grant", f"{os.environ.get('USERNAME', 'Everyone')}:F"],
                capture_output=True, timeout=10,
            )
            return True
        except Exception as e:
            logger.debug("取所有权失败 %s: %s", path, e)
            return False

    # ======================== 文件删除 ========================

    def _safe_delete_file(self, file_path: str, dry_run: bool = False,
                           use_quarantine: bool = True, category: str = "") -> Tuple[bool, int, Optional[str]]:
        """安全删除单个文件。隔离模式开启且非模拟时，移入隔离区而非永久删除。

        Returns:
            (是否成功, 释放字节数, 隔离项id|None)
        """
        if not os.path.exists(file_path):
            return False, 0, None

        if self._is_protected(file_path):
            return False, 0, None

        if is_file_in_use(file_path):
            logger.debug("文件被占用，跳过: %s", file_path)
            return False, 0, None

        if self._cancelled:
            return False, 0, None

        # 大文件保护
        if self._is_large(file_path):
            logger.info("文件过大，跳过保护: %s", file_path)
            return False, 0, None

        try:
            file_size = os.path.getsize(file_path)
        except OSError as e:
            logger.debug("无法获取文件大小: %s - %s", file_path, e)
            return False, 0, None

        if dry_run:
            logger.debug("模拟删除: %s (%s)", file_path, format_size(file_size))
            return True, file_size, None

        # 隔离模式：移入隔离区（可一键恢复），失败才回退永久删除
        if use_quarantine:
            qid = self._quarantine.move_to_quarantine(file_path, category=category)
            if qid:
                return True, file_size, qid
            logger.warning("隔离失败，回退永久删除: %s", file_path)

        for attempt in range(self.MAX_RETRY + 1):
            try:
                os.remove(file_path)
                logger.debug("成功删除: %s (%s)", file_path, format_size(file_size))
                return True, file_size, None
            except PermissionError:
                try:
                    os.chmod(file_path, 0o777)
                    os.remove(file_path)
                    logger.debug("去除只读后成功删除: %s", file_path)
                    return True, file_size, None
                except OSError:
                    self._take_ownership(file_path)
                    try:
                        os.chmod(file_path, 0o777)
                        os.remove(file_path)
                        return True, file_size, None
                    except OSError as e2:
                        if attempt < self.MAX_RETRY:
                            time.sleep(self.RETRY_DELAY)
                            continue
                        logger.warning("删除失败（权限不足）: %s - %s", file_path, e2)
                        return False, 0, None
            except OSError as e:
                if attempt < self.MAX_RETRY:
                    time.sleep(self.RETRY_DELAY)
                    continue
                logger.warning("删除失败: %s - %s", file_path, e)
                return False, 0, None

        return False, 0, None

    # ======================== 整目录删除 ========================

    def _safe_delete_dir(self, dir_path: str, dry_run: bool = False,
                          use_quarantine: bool = True, category: str = "") -> Tuple[bool, int, Optional[str]]:
        """安全删除整个目录（含子目录与文件）。清理后等效于"清空"该目录。

        隔离模式开启且非模拟时，整目录移入隔离区（可一键恢复），
        原始位置不再残留。隔离关闭时则 rmtree 后重建空目录。

        Args:
            dir_path: 目录路径。
            dry_run: True 表示模拟删除。
            use_quarantine: 是否使用隔离区。
            category: 类别名（记录用）。

        Returns:
            (是否成功, 释放的字节数)。
        """
        if not os.path.exists(dir_path):
            return False, 0, None

        if self._is_protected(dir_path):
            logger.debug("目录受保护，跳过: %s", dir_path)
            return False, 0, None

        if self._cancelled:
            return False, 0, None

        # 计算目录大小（用于统计）
        try:
            total_size = self._calc_dir_size_for_clean(dir_path)
        except OSError as e:
            logger.debug("无法计算目录大小: %s - %s", dir_path, e)
            total_size = 0

        if dry_run:
            logger.debug("模拟删除目录: %s (%s)", dir_path, format_size(total_size))
            return True, total_size, None

        # 隔离模式：整目录移入隔离区
        if use_quarantine:
            qid = self._quarantine.move_to_quarantine(dir_path, category=category)
            if qid:
                logger.info("已隔离整目录: %s (%s)", dir_path, format_size(total_size))
                return True, total_size, qid
            logger.warning("隔离失败，回退永久删除: %s", dir_path)

        try:
            shutil.rmtree(dir_path, ignore_errors=True)
            # 重建空目录，保证依赖该目录的应用正常运行
            try:
                os.makedirs(dir_path, exist_ok=True)
            except OSError:
                pass
            logger.info("成功整目录清理: %s (%s)", dir_path, format_size(total_size))
            return True, total_size, None
        except OSError as e:
            logger.warning("整目录删除失败: %s - %s", dir_path, e)
            # 尝试取所有权后重试
            self._take_ownership(dir_path)
            try:
                shutil.rmtree(dir_path, ignore_errors=True)
                os.makedirs(dir_path, exist_ok=True)
                return True, total_size, None
            except OSError as e2:
                logger.warning("重试整目录删除仍失败: %s - %s", dir_path, e2)
                return False, 0, None

    def _calc_dir_size_for_clean(self, dir_path: str) -> int:
        """计算目录大小（用于整目录清理统计）。"""
        total = 0
        try:
            with os.scandir(dir_path) as entries:
                for entry in entries:
                    if self._cancelled:
                        break
                    try:
                        if entry.is_file(follow_symlinks=False):
                            if self._is_protected(entry.path):
                                continue
                            try:
                                total += entry.stat(follow_symlinks=False).st_size
                            except OSError:
                                pass
                        elif entry.is_dir(follow_symlinks=False):
                            total += self._calc_dir_size_for_clean(entry.path)
                    except (OSError, PermissionError):
                        continue
        except (PermissionError, OSError) as e:
            logger.debug("无法访问目录统计大小 %s: %s", dir_path, e)
        return total

    # ======================== 清理后删除空父目录 ========================

    def _remove_empty_parent_dirs(self, start_path: str, stop_path: str):
        """清理后递归删除空的父目录（最多删到 stop_path 的上一级）。

        Args:
            start_path: 被删除文件/目录的父路径。
            stop_path: 停止边界（不删除此目录及其以上）。
        """
        current = os.path.dirname(start_path)
        stop_norm = normalize_path(stop_path)

        while current and normalize_path(current) != stop_norm:
            if not os.path.exists(current):
                # 当前目录已不存在，继续向上
                parent = os.path.dirname(current)
                if parent == current:
                    break
                current = parent
                continue
            try:
                # 仅当目录为空时删除
                if not any(os.scandir(current)):
                    os.rmdir(current)
                    logger.debug("删除空目录: %s", current)
                    current = os.path.dirname(current)
                else:
                    break  # 目录非空，停止
            except (OSError, PermissionError):
                break

    # ======================== 主清理流程 ========================

    def clean_categories(
        self, categories: Dict[str, ScanCategory], dry_run: bool = False,
        use_quarantine: bool = True,
    ) -> CleanResult:
        """清理指定类别的垃圾文件。

        v4.0 更新：新增隔离模式（use_quarantine）。开启时删除改"移入隔离区"，
        记录隔离项 id，支持一键恢复（撤销），彻底杜绝误删不可逆。

        Args:
            categories: 要清理的类别字典 {类别名: ScanCategory}。
            dry_run: True 表示模拟清理（不实际删除文件）。
            use_quarantine: True（默认）表示删除改移入隔离区；False 则永久删除。

        Returns:
            CleanResult 清理结果统计。
        """
        if self._is_cleaning:
            logger.warning("清理正在进行中，跳过重复请求")
            return CleanResult()

        self._is_cleaning = True
        self._cancelled = False
        result = CleanResult(dry_run=dry_run)

        try:
            # 分类处理
            recycle_category = None
            dir_categories: Dict[str, ScanCategory] = {}
            file_categories: Dict[str, ScanCategory] = {}
            command_categories: Dict[str, ScanCategory] = {}

            for category_name, category in categories.items():
                if not (category.enabled and category.files):
                    continue
                ct = getattr(category, "clean_target", "files")
                if ct == "shell":
                    recycle_category = category
                elif ct == "dir":
                    dir_categories[category_name] = category
                elif ct == "command":
                    command_categories[category_name] = category
                else:
                    file_categories[category_name] = category

            # 1. 处理普通文件类别
            for cat_idx, (category_name, category) in enumerate(file_categories.items()):
                if self._cancelled:
                    break
                self._clean_one_file_category(category_name, category, result, dry_run, use_quarantine)

            # 2. 处理整目录类别
            for cat_idx, (category_name, category) in enumerate(dir_categories.items()):
                if self._cancelled:
                    break
                self._clean_one_dir_category(category_name, category, result, dry_run, use_quarantine)

            # 3. 处理回收站（Shell API）——回收站本身已可恢复，不走隔离
            if recycle_category and not self._cancelled:
                self._clean_recycle_bin(recycle_category, result, dry_run)

            # 4. 处理系统命令类别（WinSxS / 还原点 / 休眠 / Windows.old）
            for cat_idx, (category_name, category) in enumerate(command_categories.items()):
                if self._cancelled:
                    break
                self._clean_one_command_category(category_name, category, result, dry_run)

        finally:
            self._is_cleaning = False
            self._cancelled = False

        logger.info(
            "%s完成: 删除 %d 项，释放 %s，跳过 %d 项",
            "模拟清理" if dry_run else "清理",
            result.files_deleted, format_size(result.size_freed), result.files_skipped,
        )

        return result

    def _clean_one_file_category(self, category_name, category, result, dry_run, use_quarantine=True):
        """清理单个文件类别。"""
        result.total_files_found += category.file_count
        result.total_size_found += category.total_size
        self._init_category_stat(result, category_name)

        logger.info("开始清理类别: %s (%d 个文件, %s)", category_name,
                    category.file_count, format_size(category.total_size))

        cat_deleted = cat_freed = cat_skipped = 0
        total = len(category.files)

        for file_idx, file_path in enumerate(category.files):
            if self._cancelled:
                break
            success, freed, qid = self._safe_delete_file(file_path, dry_run, use_quarantine, category_name)
            if success:
                cat_freed += freed
                if qid:
                    # 隔离成功：仅计入隔离统计，不计入永久删除
                    result.files_quarantined += 1
                    result.size_quarantined += freed
                    result.quarantine_ids.append(qid)
                else:
                    # 永久删除（隔离关闭或隔离失败回退）
                    cat_deleted += 1
                # 清理后删除空父目录
                if not dry_run and os.path.sep in file_path:
                    self._remove_empty_parent_dirs(
                        file_path,
                        get_category_root(category) or os.path.dirname(file_path)
                    )
            else:
                cat_skipped += 1

            if file_idx % 50 == 0 or file_idx == total - 1:
                self._report_progress(file_idx + 1, total, f"{category_name}: {file_path}")

        result.files_deleted += cat_deleted
        result.size_freed += cat_freed
        result.files_skipped += cat_skipped
        self._update_category_stat(result, category_name, cat_deleted, cat_freed, cat_skipped)
        logger.info("类别完成: %s - 删除 %d 个, 隔离 %d 个, 跳过 %d 个",
                    category_name, cat_deleted, result.files_quarantined, cat_skipped)

    def _clean_one_dir_category(self, category_name, category, result, dry_run, use_quarantine=True):
        """清理单个整目录类别。"""
        result.total_files_found += category.file_count
        result.total_size_found += category.total_size
        self._init_category_stat(result, category_name)

        logger.info("开始整目录清理: %s (%d 个目录, %s)", category_name,
                    category.file_count, format_size(category.total_size))

        cat_deleted = cat_freed = cat_skipped = 0
        total = len(category.files)

        for idx, dir_path in enumerate(category.files):
            if self._cancelled:
                break
            success, freed, qid = self._safe_delete_dir(dir_path, dry_run, use_quarantine, category_name)
            if success:
                cat_freed += freed
                if qid:
                    result.files_quarantined += 1
                    result.size_quarantined += freed
                    result.quarantine_ids.append(qid)
                else:
                    cat_deleted += 1
            else:
                cat_skipped += 1
            self._report_progress(idx + 1, total, f"{category_name}: {dir_path}")

        result.files_deleted += cat_deleted
        result.size_freed += cat_freed
        result.files_skipped += cat_skipped
        self._update_category_stat(result, category_name, cat_deleted, cat_freed, cat_skipped)
        logger.info("整目录清理完成: %s - 删除 %d 个, 隔离 %d 个, 跳过 %d 个",
                    category_name, cat_deleted, result.files_quarantined, cat_skipped)

    def _clean_recycle_bin(self, category, result, dry_run):
        """清理回收站（Shell API）。"""
        result.total_files_found += category.file_count
        result.total_size_found += category.total_size
        self._init_category_stat(result, "回收站")

        logger.info("开始清空回收站: %d 个文件 (%s)", category.file_count, format_size(category.total_size))
        try:
            if dry_run:
                logger.info("模拟清空回收站（dry_run）")
                result.files_deleted += category.file_count
                result.size_freed += category.total_size
                self._update_category_stat(result, "回收站", category.file_count, category.total_size, 0)
            else:
                success = empty_recycle_bin(hwnd=0, drive_root=None, silent=True)
                if success:
                    result.files_deleted += category.file_count
                    result.size_freed += category.total_size
                    self._update_category_stat(result, "回收站", category.file_count, category.total_size, 0)
                    logger.info("回收站清空成功")
                else:
                    result.files_skipped += category.file_count
                    self._update_category_stat(result, "回收站", 0, 0, category.file_count)
                    logger.warning("回收站清空失败（可能需要管理员权限）")
        except Exception as e:
            logger.error("清空回收站异常: %s", e)
            result.files_skipped += category.file_count
            result.errors.append(f"回收站清空失败: {e}")

    def _clean_one_command_category(self, category_name, category, result, dry_run):
        """执行系统命令式清理（WinSxS / 还原点 / 休眠 / Windows.old 等）。

        以管理员权限运行配置中的命令；dry_run 仅报告，不实际执行；
        需要管理员但未提权时记录错误并跳过。
        """
        result.total_files_found += 1
        result.total_size_found += category.total_size
        self._init_category_stat(result, category_name)

        cmd = getattr(category, "command", "")
        requires_admin = getattr(category, "requires_admin", False)

        if not cmd:
            logger.warning("命令式清理类别 %s 缺少 command 字段，跳过", category_name)
            result.files_skipped += 1
            self._update_category_stat(result, category_name, 0, 0, 1)
            return

        if dry_run:
            logger.info("模拟执行系统命令: %s", cmd)
            result.files_deleted += 1
            result.size_freed += category.total_size
            self._update_category_stat(result, category_name, 1, category.total_size, 0)
            return

        if requires_admin and not is_process_elevated():
            msg = f"{category_name}：需要管理员权限（请以管理员身份运行本程序）"
            logger.warning(msg)
            result.errors.append(msg)
            result.files_skipped += 1
            self._update_category_stat(result, category_name, 0, 0, 1)
            return

        try:
            logger.info("执行系统命令清理: %s", cmd)
            proc = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=900
            )
            if proc.returncode == 0:
                result.files_deleted += 1
                result.size_freed += category.total_size
                self._update_category_stat(result, category_name, 1, category.total_size, 0)
                logger.info("系统命令执行成功: %s", category_name)
            else:
                err = (proc.stderr or proc.stdout or "").strip()
                msg = f"{category_name}：命令返回 {proc.returncode} - {err[:200]}"
                logger.warning(msg)
                result.errors.append(msg)
                result.files_skipped += 1
                self._update_category_stat(result, category_name, 0, 0, 1)
        except subprocess.TimeoutExpired as e:
            msg = f"{category_name}：命令执行超时（{e}）"
            logger.error(msg)
            result.errors.append(msg)
            result.files_skipped += 1
            self._update_category_stat(result, category_name, 0, 0, 1)
        except Exception as e:
            msg = f"{category_name}：命令执行异常 - {e}"
            logger.error(msg)
            result.errors.append(msg)
            result.files_skipped += 1
            self._update_category_stat(result, category_name, 0, 0, 1)

    # ======================== 统计辅助 ========================

    @staticmethod
    def _init_category_stat(result, name):
        result.by_category[name] = {"deleted": 0, "freed": 0, "skipped": 0}

    @staticmethod
    def _update_category_stat(result, name, deleted, freed, skipped):
        if name not in result.by_category:
            result.by_category[name] = {"deleted": 0, "freed": 0, "skipped": 0}
        result.by_category[name]["deleted"] += deleted
        result.by_category[name]["freed"] += freed
        result.by_category[name]["skipped"] += skipped

    def clean_single_category(self, category: ScanCategory, dry_run: bool = False) -> CleanResult:
        """清理单个类别。"""
        return self.clean_categories({category.name: category}, dry_run=dry_run)


def get_category_root(category: ScanCategory) -> Optional[str]:
    """获取类别的根目录（用于清理后删空目录的边界判断）。

    从 config 读取该类别的 paths 首个路径作为边界。
    """
    try:
        from config import get_default_categories
        cfg = get_default_categories().get(category.name, {})
        paths = cfg.get("paths", [])
        if paths:
            return os.path.dirname(paths[0])
    except Exception:
        pass
    return None


class AutoCleaner:
    """自动清理管理器 v3.0。

    支持定时自动清理功能，可在后台线程中运行。
    """

    INTERVAL_PRESETS = {
        "每天": 24,
        "每周": 168,
        "每月": 720,
    }

    def __init__(self, cleaner: Cleaner, scanner=None):
        self._cleaner = cleaner
        self._scanner = scanner
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._interval_hours: int = 24
        self._on_complete: Optional[Callable[[CleanResult], None]] = None
        self._stop_event = threading.Event()
        self._dry_run: bool = False
        self._use_task_scheduler: bool = False  # v3.0：是否使用 Windows 任务计划程序

    def set_interval_hours(self, hours: int):
        self._interval_hours = max(1, hours)
        logger.info("自动清理间隔设置为 %d 小时", self._interval_hours)

    def set_dry_run(self, dry_run: bool):
        self._dry_run = dry_run
        logger.info("自动清理 dry_run 设置为 %s", dry_run)

    def set_use_task_scheduler(self, use: bool):
        """设置是否使用 Windows 任务计划程序（替代轮询线程）。"""
        self._use_task_scheduler = use

    def set_on_complete_callback(self, callback: Callable[[CleanResult], None]):
        self._on_complete = callback

    def start(self):
        if self._running:
            logger.warning("自动清理已在运行中")
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._auto_clean_loop, daemon=True)
        self._thread.start()
        logger.info("自动清理已启动，间隔 %d 小时", self._interval_hours)

    def stop(self):
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("自动清理已停止")

    def _auto_clean_loop(self):
        while self._running and not self._stop_event.is_set():
            stopped = self._stop_event.wait(timeout=self._interval_hours * 3600)
            if stopped or not self._running:
                break
            logger.info("自动清理触发")
            self._perform_auto_clean()

    def _perform_auto_clean(self):
        try:
            if self._scanner is None:
                logger.warning("自动清理需要 Scanner 实例")
                return
            scan_results = self._scanner.scan_all()
            result = self._cleaner.clean_categories(scan_results, dry_run=self._dry_run)
            logger.info("自动清理完成: 释放 %s", format_size(result.size_freed))
            if self._on_complete:
                try:
                    self._on_complete(result)
                except Exception as e:
                    logger.error("自动清理回调异常: %s", e)
        except Exception as e:
            logger.error("自动清理执行失败: %s", e)

    def perform_now(self, dry_run: bool = False) -> Optional[CleanResult]:
        if self._scanner is None:
            logger.warning("立即清理需要 Scanner 实例")
            return None
        scan_results = self._scanner.scan_all()
        result = self._cleaner.clean_categories(scan_results, dry_run=dry_run)
        if self._on_complete:
            try:
                self._on_complete(result)
            except Exception as e:
                logger.error("清理回调异常: %s", e)
        return result
