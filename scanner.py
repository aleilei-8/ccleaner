# -*- coding: utf-8 -*-
"""扫描引擎模块 v3.0

负责遍历各类垃圾目录，计算文件大小并汇总。

v3.0 重大修复（解决"扫不到、清不干净"）：
1. 删除 v2.0 的 quick_mode 不递归逻辑（凡是含 "Windows" 的路径强制顶层扫描，
   导致 C:\\Windows\\Temp、Prefetch 等嵌套目录扫到 0 文件）。
2. 改为每类别配置 scan_mode（deep 深度递归 / shallow 仅一层）。
3. 新增 clean_target 字段：files（逐个删文件）/ dir（整目录删除）。
   整目录类（Temp、缓存）扫描时只统计目录大小，清理时 rmtree 整个目录。
4. 环境变量（%LOCALAPPDATA%、%TEMP%、%APPDATA% 等）自动展开。
5. 权限不足不再静默返回 0，而是记录到 _permission_errors，供 GUI 提示用户。
6. 多盘符自动发现（D:/E: 等），覆盖所有驱动器的回收站与可写目录。
"""

import os
import re
import ctypes
import fnmatch
import logging
import threading
import subprocess
from typing import Dict, List, Optional, Callable, Set
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import (
    get_default_categories,
    get_protected_directories,
    get_protected_extensions_in_windows,
    get_protected_files,
    get_protected_user_dirs,
    get_protected_system_files_pattern,
)
from utils import (
    normalize_path, is_sub_path, get_recycle_bin_info, get_all_drives,
    format_size, is_process_elevated,
)

logger = logging.getLogger(__name__)


@dataclass
class ScanCategory:
    """单个清理类别的扫描结果。"""
    name: str = ""  # 类别名称
    description: str = ""  # 类别描述
    files: List[str] = field(default_factory=list)  # 文件路径列表（或目录路径，取决于 clean_target）
    total_size: int = 0  # 总大小（字节）
    file_count: int = 0  # 文件数量（或目录数量）
    enabled: bool = True  # 是否默认选中
    tab: str = "quick"  # 所属 Tab：quick|deep|analyze
    clean_target: str = "files"  # 清理目标：files（逐个删文件）/ dir（整目录删除）/ shell（回收站）/ command（系统命令）
    command: str = ""  # 系统命令清理时的命令字符串
    requires_admin: bool = False  # 是否需要管理员权限
    risk_level: str = ""  # 风险等级：low/medium/high


class Scanner:
    """垃圾文件扫描引擎 v3.0。

    遍历各类别的目标路径，收集垃圾文件/目录信息，
    同时执行安全检查以排除受保护的文件。
    """

    # 最大递归深度（防止符号链接无限递归，使用 visited 集合双重保险）
    MAX_DEPTH = 25

    def __init__(self):
        """初始化扫描器，加载保护规则。"""
        self._protected_dirs: set = get_protected_directories()
        self._protected_extensions: set = get_protected_extensions_in_windows()
        self._protected_files: set = get_protected_files()
        self._protected_user_dirs: List[str] = get_protected_user_dirs()
        self._protected_patterns: List[str] = get_protected_system_files_pattern()
        self._categories_config: Dict = get_default_categories()
        self._lock = threading.Lock()
        self._is_scanning: bool = False
        self._cancelled: bool = False
        self._progress_callback: Optional[Callable[[int, int, str], None]] = None
        # v3.0 新增：记录因权限不足而被跳过的目录（供 GUI 提示）
        self._permission_errors: Set[str] = set()

    def set_progress_callback(self, callback: Callable[[int, int, str], None]):
        """设置进度回调函数。

        Args:
            callback: 回调函数，参数为 (当前进度, 总数, 当前类别名)。
        """
        self._progress_callback = callback

    @property
    def is_scanning(self) -> bool:
        """当前是否正在扫描。"""
        return self._is_scanning

    def get_permission_errors(self) -> List[str]:
        """获取扫描过程中因权限不足被跳过的目录列表。"""
        with self._lock:
            return sorted(self._permission_errors)

    def clear_permission_errors(self):
        """清空权限错误记录。"""
        with self._lock:
            self._permission_errors.clear()

    def cancel(self):
        """取消正在进行的扫描操作。"""
        self._cancelled = True
        logger.info("扫描操作已被用户取消")

    def _report_progress(self, current: int, total: int, category_name: str):
        """报告扫描进度。"""
        if self._progress_callback:
            try:
                self._progress_callback(current, total, category_name)
            except Exception as e:
                logger.warning("进度回调异常: %s", e)

    # ======================== 环境变量展开 ========================

    @staticmethod
    def expand_env_path(raw_path: str) -> List[str]:
        """展开路径中的环境变量，返回所有可能的实际路径。

        Args:
            raw_path: 可能包含 %VAR% 或 {VAR} 占位符的路径。

        Returns:
            展开后的路径列表（已去重，保留存在的路径；若不存在也保留原始展开的）。
        """
        # 处理 %VAR% 形式
        expanded = os.path.expandvars(raw_path)
        # 处理 {LOCALAPPDATA} 等形式（部分配置使用花括号）
        if "{" in expanded and "}" in expanded:
            try:
                expanded = expanded.format(
                    LOCALAPPDATA=os.environ.get("LOCALAPPDATA", ""),
                    APPDATA=os.environ.get("APPDATA", ""),
                    USERPROFILE=os.environ.get("USERPROFILE", ""),
                    TEMP=os.environ.get("TEMP", ""),
                    TMP=os.environ.get("TMP", ""),
                    WINDIR=os.environ.get("WINDIR", r"C:\Windows"),
                    USERNAME=os.environ.get("USERNAME", ""),
                )
            except (KeyError, IndexError):
                pass
        results = [expanded]
        return results

    # ======================== 安全保护检查 ========================

    def _is_protected(self, file_path: str) -> bool:
        """检查文件是否受保护。

        Args:
            file_path: 文件完整路径。

        Returns:
            True 表示文件受保护，不应被清理。
        """
        norm_path = normalize_path(file_path)

        # 1. 检查系统关键文件列表
        if norm_path in self._protected_files:
            return True

        # 1.5 检查系统文件模式（pagefile.sys, swapfile.sys 等）
        filename_lower = os.path.basename(file_path).lower()
        for pattern in self._protected_patterns:
            if fnmatch.fnmatch(filename_lower, pattern.lower()):
                logger.debug("文件匹配受保护模式 %s: %s", pattern, file_path)
                return True

        # 2. 检查是否在受保护的目录下
        for protected_dir in self._protected_dirs:
            if is_sub_path(file_path, protected_dir):
                return True

        # 3. 检查 Windows 目录下受保护的扩展名
        if self._is_windows_dir(file_path):
            ext = os.path.splitext(file_path)[1].lower()
            if ext in self._protected_extensions:
                logger.debug("文件在 Windows 目录下且为受保护扩展名: %s (%s)", file_path, ext)
                return True

        return False

    @staticmethod
    def _is_windows_dir(file_path: str) -> bool:
        """检查文件是否位于 Windows 目录下。"""
        norm = normalize_path(file_path)
        return norm.startswith(normalize_path(r"C:\Windows"))

    # ======================== 单目录递归扫描 ========================

    def _scan_single_path_scandir(
        self,
        scan_path: str,
        extensions: Optional[List[str]] = None,
        scan_mode: str = "deep",
        max_depth: int = MAX_DEPTH,
        current_depth: int = 0,
        visited: Optional[Set[str]] = None,
        skip_user_dirs: bool = False,
    ) -> tuple:
        """使用 os.scandir 递归扫描单个目录。

        v3.0 修复：默认深度递归（不再有 quick_mode 不递归的 bug）。
        scan_mode="shallow" 时仅扫描一层（用于明确的顶层缓存目录，避免过深）。
        权限错误会记录到 _permission_errors，不再静默返回 0。

        Args:
            scan_path: 要扫描的目录路径。
            extensions: 可选的文件扩展名过滤列表。
            scan_mode: "deep"（递归）/ "shallow"（仅一层）。
            max_depth: 最大递归深度。
            current_depth: 当前递归深度。
            visited: 已访问的 inode 集合（防止符号链接循环）。

        Returns:
            (found_files: List[str], total_size: int)
        """
        found_files: List[str] = []
        total_size: int = 0

        if not os.path.exists(scan_path):
            logger.debug("扫描路径不存在，跳过: %s", scan_path)
            return found_files, total_size

        if current_depth > max_depth:
            logger.debug("达到最大递归深度，停止: %s", scan_path)
            return found_files, total_size

        if self._cancelled:
            logger.debug("扫描被取消，停止: %s", scan_path)
            return found_files, total_size

        if visited is None:
            visited = set()

        try:
            with os.scandir(scan_path) as entries:
                entries_list = list(entries)
        except (PermissionError, OSError) as e:
            # v3.0：记录权限错误（不再静默吞掉）
            with self._lock:
                self._permission_errors.add(scan_path)
            logger.debug("无权限访问目录（需管理员）: %s - %s", scan_path, e)
            return found_files, total_size

        for entry in entries_list:
            if self._cancelled:
                break

            try:
                if entry.is_file(follow_symlinks=False):
                    file_path = entry.path

                    # 安全检查：跳过受保护文件
                    if self._is_protected(file_path):
                        continue

                    # 扩展名过滤
                    if extensions:
                        matched = False
                        file_ext = os.path.splitext(entry.name)[1].lower()
                        for ext_pattern in extensions:
                            pattern_lower = ext_pattern.lower()
                            if file_ext == pattern_lower:
                                matched = True
                                break
                            if '*' in pattern_lower and fnmatch.fnmatch(entry.name.lower(), pattern_lower):
                                matched = True
                                break
                        if not matched:
                            continue

                    found_files.append(file_path)
                    try:
                        total_size += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass

                elif entry.is_dir(follow_symlinks=False):
                    if scan_mode == "shallow":
                        # shallow 模式完全不递归任何子目录
                        continue

                    # 跳过受保护目录（安全 + 效率）：系统关键目录、用户文档目录等
                    try:
                        if self._is_protected_dir(entry.path, skip_user_dirs):
                            continue
                    except Exception:
                        pass

                    # 防止符号链接循环
                    try:
                        real_path = os.path.realpath(entry.path)
                        if real_path in visited:
                            continue
                        visited.add(real_path)
                    except OSError:
                        pass

                    # 深度递归
                    sub_files, sub_size = self._scan_single_path_scandir(
                        entry.path, extensions, scan_mode, max_depth,
                        current_depth + 1, visited, skip_user_dirs
                    )
                    found_files.extend(sub_files)
                    total_size += sub_size

            except (OSError, PermissionError) as e:
                logger.debug("处理条目异常: %s - %s", getattr(entry, 'path', 'unknown'), e)
                continue

        return found_files, total_size

    # ======================== 整目录大小统计 ========================

    def _calc_dir_size(self, dir_path: str, visited: Optional[Set[str]] = None) -> int:
        """递归计算目录总大小（用于整目录清理类的统计）。

        Args:
            dir_path: 目录路径。
            visited: 已访问 inode 集合。

        Returns:
            目录总大小（字节）。
        """
        if not os.path.exists(dir_path):
            return 0

        if visited is None:
            visited = set()

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
                            try:
                                real_path = os.path.realpath(entry.path)
                                if real_path in visited:
                                    continue
                                visited.add(real_path)
                            except OSError:
                                pass
                            total += self._calc_dir_size(entry.path, visited)
                    except (OSError, PermissionError):
                        continue
        except (PermissionError, OSError):
            with self._lock:
                self._permission_errors.add(dir_path)
            logger.debug("无权限统计目录大小: %s", dir_path)
        return total

    # ======================== 类别扫描 ========================

    def _scan_category(self, category_name: str, category_config: Dict) -> ScanCategory:
        """扫描单个清理类别。

        v3.0 更新：支持 Shell API（回收站）、clean_target（dir/files）、
        环境变量展开、多盘符。

        Args:
            category_name: 类别名称。
            category_config: 类别配置字典。

        Returns:
            ScanCategory 扫描结果对象。
        """
        description = category_config.get("description", "")
        tab = category_config.get("tab", "quick")
        clean_target = category_config.get("clean_target", "files")

        # 特殊处理：回收站使用 Shell API 扫描
        if category_config.get("use_shell_api") == "recycle_bin":
            return self._scan_recycle_bin(category_name, description)

        # 命令式系统级清理（WinSxS / 还原点 / 休眠 / Windows.old）
        if category_config.get("clean_target") == "command":
            return self._scan_command_category(category_name, category_config)

        paths = category_config.get("paths", [])
        extensions = category_config.get("extensions")
        scan_mode = category_config.get("scan_mode", "deep")

        # 全盘残留临时文件清扫（sweep 模式：多根目录按扩展名递归）
        if scan_mode == "sweep":
            return self._scan_sweep_category(category_name, category_config)

        # v3.0：展开环境变量，并支持多盘符自动发现
        expanded_paths: List[str] = []
        for raw_path in paths:
            expanded = self.expand_env_path(raw_path)
            for p in expanded:
                if p and p.strip():
                    expanded_paths.append(p.strip())

        # 整目录清理类：统计目录大小即可
        if clean_target == "dir":
            total_size = 0
            dir_list: List[str] = []
            for p in expanded_paths:
                if os.path.exists(p):
                    try:
                        size = self._calc_dir_size(p)
                        total_size += size
                        dir_list.append(p)
                        logger.info("整目录清理类 [%s]: %s 大小 %s", category_name, p, format_size(size))
                    except Exception as e:
                        logger.warning("统计目录大小失败 %s: %s", p, e)
                else:
                    logger.debug("整目录路径不存在，跳过: %s", p)

            return ScanCategory(
                name=category_name,
                description=description,
                files=dir_list,
                total_size=total_size,
                file_count=len(dir_list),
                enabled=True,
                tab=tab,
                clean_target="dir",
            )

        # 文件清理类：递归收集文件
        all_files: List[str] = []
        total_size: int = 0
        for scan_path in expanded_paths:
            files, size = self._scan_single_path_scandir(
                scan_path, extensions, scan_mode=scan_mode
            )
            all_files.extend(files)
            total_size += size

            if self._cancelled:
                break

        return ScanCategory(
            name=category_name,
            description=description,
            files=all_files,
            total_size=total_size,
            file_count=len(all_files),
            enabled=True,
            tab=tab,
            clean_target="files",
        )

    def _scan_recycle_bin(self, category_name: str, description: str) -> ScanCategory:
        """使用 Shell API 扫描所有驱动器的回收站。

        Args:
            category_name: 类别名称。
            description: 类别描述。

        Returns:
            ScanCategory 扫描结果对象。
        """
        total_count = 0
        total_size_bytes = 0
        all_files: List[str] = []

        drives = get_all_drives()
        logger.info("检测到 %d 个驱动器，开始扫描回收站", len(drives))

        for drive in drives:
            if self._cancelled:
                break
            try:
                count, size = get_recycle_bin_info(drive)
                if count > 0:
                    logger.info("回收站扫描: %s - %d 个文件，%s", drive, count, format_size(size))
                    total_count += count
                    total_size_bytes += size
                    for i in range(min(count, 100)):
                        all_files.append(f"{drive}$Recycle.Bin\\item_{i + 1}")
                    if count > 100:
                        remaining = count - 100
                        all_files.append(f"{drive}$Recycle.Bin\\... 还有 {remaining} 个文件")
            except Exception as e:
                logger.warning("扫描驱动器 %s 回收站失败: %s", drive, e)

        result = ScanCategory(
            name=category_name,
            description=description,
            files=all_files,
            total_size=total_size_bytes,
            file_count=total_count,
            enabled=True,
            tab="quick",
            clean_target="shell",
        )

        if total_count > 0:
            logger.info("回收站扫描完成: 共 %d 个文件，占用 %s", total_count, format_size(total_size_bytes))
        else:
            logger.info("回收站为空")

        return result

    # ======================== 受保护目录判断 ========================

    def _is_protected_dir(self, dir_path: str, skip_user_dirs: bool = False) -> bool:
        """判断目录是否受保护（不应被递归/清理）。

        Args:
            dir_path: 目录路径。
            skip_user_dirs: 是否把用户文档目录（Documents/Desktop/...）也视为受保护。

        Returns:
            True 表示受保护。
        """
        norm = normalize_path(dir_path)
        for protected_dir in self._protected_dirs:
            if norm == protected_dir or is_sub_path(dir_path, protected_dir):
                return True
        if skip_user_dirs:
            base = os.path.basename(norm)
            if base.lower() in {d.lower() for d in self._protected_user_dirs}:
                return True
        return False

    # ======================== 命令式系统级清理扫描 ========================

    def _scan_command_category(self, category_name: str, category_config: Dict) -> ScanCategory:
        """扫描命令式系统清理类别。

        通过 analyze_command 预估可释放空间（如 WinSxS 的 Dism AnalyzeComponentStore），
        或在未提供时按 RAM / Windows.old 目录大小估算。未以管理员运行时仅作提示、不预估。

        Returns:
            ScanCategory 结果（clean_target="command"）。
        """
        description = category_config.get("description", "")
        cmd = category_config.get("command", "")
        analyze_cmd = category_config.get("analyze_command")
        parser = category_config.get("analyze_parser")
        estimate_ram = category_config.get("estimate_ram", False)
        requires_admin = category_config.get("requires_admin", False)
        risk = category_config.get("risk_level", "low")
        tab = category_config.get("tab", "deep")

        total_size = 0
        note = ""

        if requires_admin and not is_process_elevated():
            note = "（需以管理员身份运行才能扫描/清理）"
        else:
            try:
                if analyze_cmd:
                    proc = subprocess.run(
                        analyze_cmd, shell=True, capture_output=True, text=True, timeout=120
                    )
                    txt = (proc.stdout or "") + (proc.stderr or "")
                    sz = self._parse_analyze(parser, txt)
                    if sz is not None:
                        total_size = sz
                elif estimate_ram:
                    total_size = self._get_total_ram_bytes()
                elif "windows.old" in cmd.lower() and os.path.exists("C:\\Windows.old"):
                    total_size = self._calc_dir_size("C:\\Windows.old")
            except Exception as e:
                logger.warning("分析系统命令类别失败 %s: %s", category_name, e)

        return ScanCategory(
            name=category_name,
            description=description + note,
            files=["__command__"],
            total_size=total_size,
            file_count=1,
            enabled=True,
            tab=tab,
            clean_target="command",
            command=cmd,
            requires_admin=requires_admin,
            risk_level=risk,
        )

    @staticmethod
    def _parse_analyze(parser: Optional[str], text: str) -> Optional[int]:
        """解析 analyze_command 输出，提取可释放字节数。

        目前支持 Dism AnalyzeComponentStore 的『可回收的空间』字段
        （兼容中文与英文输出）。
        """
        if not text:
            return None
        if parser == "dism_reclaim":
            patterns = [
                r"可回收的空间[^\d]*?([\d.,]+)\s*GB",
                r"Space can be reclaimed[^\d]*?([\d.,]+)\s*GB",
                r"可回收的空间[^\d]*?([\d.,]+)\s*MB",
                r"Space can be reclaimed[^\d]*?([\d.,]+)\s*MB",
            ]
            for i, pat in enumerate(patterns):
                m = re.search(pat, text, re.IGNORECASE)
                if m:
                    try:
                        val = float(m.group(1).replace(",", ""))
                        unit = "GB" if "GB" in pat else "MB"
                        return int(val * (1024 ** 3 if unit == "GB" else 1024 ** 2))
                    except ValueError:
                        continue
        return None

    @staticmethod
    def _get_total_ram_bytes() -> int:
        """获取物理内存总量（字节），用于估算 hiberfil.sys 大小。"""
        try:
            class MEMORYSTATUS(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                ]
            st = MEMORYSTATUS()
            st.dwLength = ctypes.sizeof(st)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return int(st.ullTotalPhys)
        except Exception:
            return 0

    # ======================== 全盘残留临时文件清扫（sweep） ========================

    def _scan_sweep_category(self, category_name: str, category_config: Dict) -> ScanCategory:
        """多根目录、按扩展名递归清扫（sweep 模式）。

        用于『用户残留临时文件清扫』『系统日志与调试残留』等：
        展开所有根路径，对匹配扩展名的文件逐一收集，跳过受保护目录与用户文档目录。
        """
        description = category_config.get("description", "")
        tab = category_config.get("tab", "deep")
        extensions = category_config.get("extensions")
        skip_user = category_config.get("sweep_skip_user_dirs", False)
        max_depth = category_config.get("sweep_max_depth", 6)

        roots: List[str] = []
        for raw in category_config.get("paths", []):
            for p in self.expand_env_path(raw):
                if p and p.strip():
                    roots.append(p.strip())

        # 过滤掉整体受保护的目录（如误配到系统目录）
        roots = [r for r in roots if not self._is_protected_dir(r, skip_user)]

        all_files: List[str] = []
        total: int = 0
        for root in roots:
            if self._cancelled:
                break
            if not os.path.exists(root):
                continue
            files, size = self._scan_single_path_scandir(
                root, extensions, scan_mode="deep",
                max_depth=max_depth, current_depth=0,
                skip_user_dirs=skip_user,
            )
            all_files.extend(files)
            total += size
            logger.info("sweep 类别 [%s] 根 %s：%d 个文件，%s",
                        category_name, root, len(files), format_size(size))

        return ScanCategory(
            name=category_name,
            description=description,
            files=all_files,
            total_size=total,
            file_count=len(all_files),
            enabled=True,
            tab=tab,
            clean_target="files",
        )

    # ======================== 全量扫描 ========================

    def scan_all(self, tab_filter: Optional[str] = None) -> Dict[str, ScanCategory]:
        """扫描所有清理类别。

        Args:
            tab_filter: 可选，仅扫描指定 tab 的类别（"quick", "deep", "analyze"）。

        Returns:
            字典 {类别名: ScanCategory}，包含各类别的扫描结果。
        """
        if self._is_scanning:
            logger.warning("扫描正在进行中，跳过重复请求")
            return {}

        self._is_scanning = True
        self._cancelled = False
        self.clear_permission_errors()
        results: Dict[str, ScanCategory] = {}

        category_names = [
            name for name in self._categories_config.keys()
            if tab_filter is None or self._categories_config[name].get("tab", "quick") == tab_filter
        ]
        total_categories = len(category_names)

        logger.info("开始扫描垃圾文件，共 %d 个类别（tab=%s）", total_categories, tab_filter or "all")

        try:
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_name = {}
                for name in category_names:
                    config = self._categories_config[name]
                    future = executor.submit(self._scan_category, name, config)
                    future_to_name[future] = name

                completed = 0
                for future in as_completed(future_to_name):
                    if self._cancelled:
                        for f in future_to_name:
                            f.cancel()
                        break

                    category_name = future_to_name[future]
                    try:
                        result = future.result()
                        results[category_name] = result
                        logger.info(
                            "扫描完成: %s - %d 项, %s",
                            category_name, result.file_count,
                            self._format_size_static(result.total_size),
                        )
                    except Exception as e:
                        logger.error("扫描类别 %s 失败: %s", category_name, e)
                        results[category_name] = ScanCategory(
                            name=category_name,
                            description=self._categories_config[category_name].get("description", ""),
                            files=[],
                            total_size=0,
                            file_count=0,
                            enabled=True,
                            clean_target=self._categories_config[category_name].get("clean_target", "files"),
                        )

                    completed += 1
                    self._report_progress(completed, total_categories, category_name)

        except Exception as e:
            logger.error("扫描过程异常: %s", e)
        finally:
            self._is_scanning = False

        total_files = sum(r.file_count for r in results.values())
        total_size = sum(r.total_size for r in results.values())
        logger.info("扫描完成，共发现 %d 个垃圾条目，占用 %s", total_files, self._format_size_static(total_size))

        return results

    def scan_categories(self, category_names: List[str]) -> Dict[str, ScanCategory]:
        """扫描指定的清理类别。

        Args:
            category_names: 要扫描的类别名称列表。

        Returns:
            字典 {类别名: ScanCategory}。
        """
        self._is_scanning = True
        self._cancelled = False
        self.clear_permission_errors()
        results: Dict[str, ScanCategory] = {}
        total = len(category_names)
        completed = 0

        try:
            for name in category_names:
                if self._cancelled:
                    break
                if name in self._categories_config:
                    result = self._scan_category(name, self._categories_config[name])
                    results[name] = result
                completed += 1
                self._report_progress(completed, total, name)
        except Exception as e:
            logger.error("扫描指定类别异常: %s", e)
        finally:
            self._is_scanning = False

        return results

    @staticmethod
    def _format_size_static(size_bytes: int) -> str:
        """格式化文件大小（静态方法，避免循环导入）。"""
        if size_bytes <= 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB"]
        idx = 0
        size = float(size_bytes)
        while size >= 1024.0 and idx < len(units) - 1:
            size /= 1024.0
            idx += 1
        if idx >= 2:
            return f"{size:.2f} {units[idx]}"
        else:
            return f"{size:.1f} {units[idx]}"
