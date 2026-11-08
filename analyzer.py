# -*- coding: utf-8 -*-
"""空间分析模块 v2.0

提供 C 盘空间分析功能：
- 目录大小分析（treemap 数据）
- 大文件查找（>1GB 文件列表）
- 重复文件查找（MD5 去重）
- 空文件夹查找
"""

import os
import logging
import threading
from typing import Dict, List, Tuple, Optional, Callable
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

from utils import format_size, find_large_files, find_duplicate_files

logger = logging.getLogger(__name__)


@dataclass
class DirSizeInfo:
    """目录大小信息。"""
    path: str
    name: str
    size_bytes: int = 0
    file_count: int = 0
    sub_dirs: List['DirSizeInfo'] = field(default_factory=list)
    depth: int = 0


@dataclass
class LargeFileInfo:
    """大文件信息。"""
    path: str
    size_bytes: int
    size_str: str = ""

    def __post_init__(self):
        self.size_str = format_size(self.size_bytes)


@dataclass
class DuplicateGroup:
    """重复文件组。"""
    file_hash: str
    files: List[str]
    file_size_bytes: int
    wasted_space: int  # 浪费的空间（重复文件总大小 - 1份）
    file_size_str: str = ""

    def __post_init__(self):
        self.file_size_str = format_size(self.file_size_bytes)


@dataclass
class SpaceAnalysis:
    """空间分析结果。"""
    total_size: int = 0
    total_files: int = 0
    dir_tree: List[DirSizeInfo] = field(default_factory=list)
    large_files: List[LargeFileInfo] = field(default_factory=list)
    duplicate_groups: List[DuplicateGroup] = field(default_factory=list)
    empty_dirs: List[str] = field(default_factory=list)
    wasted_total: int = 0  # 可回收的总空间


class SpaceAnalyzer:
    """C 盘空间分析器 v2.0。

    提供全面的磁盘空间分析功能。
    """

    def __init__(self, drive: str = "C:\\"):
        """初始化空间分析器。

        Args:
            drive: 要分析的驱动器盘符。
        """
        self.drive = drive
        self._is_analyzing: bool = False
        self._cancelled: bool = False
        self._progress_callback: Optional[Callable[[str, int, str], None]] = None

    def set_progress_callback(self, callback: Callable[[str, int, str], None]):
        """设置进度回调。

        Args:
            callback: 回调函数，参数为 (阶段名, 进度百分比, 详细信息)。
        """
        self._progress_callback = callback

    def cancel(self):
        """取消分析操作。"""
        self._cancelled = True
        logger.info("空间分析已被取消")

    @property
    def is_analyzing(self) -> bool:
        return self._is_analyzing

    def _report(self, stage: str, percent: int, detail: str = ""):
        """报告分析进度。"""
        if self._progress_callback:
            try:
                self._progress_callback(stage, percent, detail)
            except Exception as e:
                logger.warning("进度回调异常: %s", e)

    def run_full_analysis(self, large_file_threshold_mb: int = 1024) -> SpaceAnalysis:
        """执行完整的空间分析。

        Args:
            large_file_threshold_mb: 大文件阈值（MB）。

        Returns:
            SpaceAnalysis 对象包含完整分析结果。
        """
        self._is_analyzing = True
        self._cancelled = False
        result = SpaceAnalysis()

        try:
            # 1. 目录大小分析
            self._report("目录大小分析", 5, "正在分析目录结构...")
            top_dirs = self._analyze_directory_sizes()
            result.dir_tree = top_dirs
            for d in top_dirs:
                result.total_size += d.size_bytes
                result.total_files += d.file_count

            if self._cancelled:
                return result

            # 2. 大文件查找
            self._report("大文件查找", 40, f"正在查找 > {large_file_threshold_mb}MB 的文件...")
            large_files = find_large_files(
                self.drive,
                min_size_mb=large_file_threshold_mb,
                max_depth=8,
                cancel_event=None,
            )
            for path, size in large_files:
                result.large_files.append(LargeFileInfo(path=path, size_bytes=size))

            if self._cancelled:
                return result

            # 3. 重复文件查找（仅扫描用户目录和 ProgramData，避免扫描整个 C 盘）
            self._report("重复文件查找", 70, "正在查找重复文件...")
            user_profile = os.environ.get("USERPROFILE", r"C:\Users")
            scan_dirs = [
                os.path.join(user_profile, "Documents"),
                os.path.join(user_profile, "Downloads"),
                os.path.join(user_profile, "Desktop"),
                r"C:\ProgramData",
            ]
            # 只扫描存在的目录
            valid_dirs = [d for d in scan_dirs if os.path.exists(d)]

            if valid_dirs:
                dup_map = find_duplicate_files(
                    scan_paths=valid_dirs,
                    min_size_mb=1,
                    cancel_event=None,
                )
                wasted = 0
                for file_hash, files in dup_map.items():
                    if len(files) > 1:
                        file_size = os.path.getsize(files[0]) if os.path.exists(files[0]) else 0
                        wasted += file_size * (len(files) - 1)
                        result.duplicate_groups.append(
                            DuplicateGroup(
                                file_hash=file_hash,
                                files=files,
                                file_size_bytes=file_size,
                                wasted_space=file_size * (len(files) - 1),
                            )
                        )
                result.wasted_total += wasted

                self._report("重复文件查找", 85, f"找到 {len(result.duplicate_groups)} 组重复文件")

            # 4. 空文件夹查找
            self._report("空文件夹查找", 90, "正在查找空文件夹...")
            # 只检查顶级用户目录
            for d in valid_dirs:
                for root, dirs, files in os.walk(d, topdown=False):
                    if self._cancelled:
                        break
                    try:
                        if not os.listdir(root):
                            result.empty_dirs.append(root)
                            os.rmdir(root)  # 尝试删除空文件夹
                    except OSError:
                        continue

        except Exception as e:
            logger.error("空间分析异常: %s", e)
        finally:
            self._is_analyzing = False
            self._report("完成", 100, "分析完成")

        return result

    def _analyze_directory_sizes(self) -> List[DirSizeInfo]:
        """分析 C 盘顶级目录的大小。

        Returns:
            DirSizeInfo 列表，按大小降序排序。
        """
        results = []

        # 需要分析的顶级目录（避免扫描受保护的）
        top_dirs = [
            (r"C:\Windows", "Windows"),
            (r"C:\Program Files", "Program Files"),
            (r"C:\Program Files (x86)", "Program Files (x86)"),
            (r"C:\Users", "Users"),
            (r"C:\ProgramData", "ProgramData"),
        ]

        for dir_path, dir_name in top_dirs:
            if self._cancelled:
                break
            if not os.path.exists(dir_path):
                continue

            self._report("目录大小分析", 5, f"分析 {dir_name}...")
            info = DirSizeInfo(path=dir_path, name=dir_name)
            info.size_bytes, info.file_count = self._get_dir_size(dir_path, max_depth=4)
            results.append(info)

        # 按大小降序排序
        results.sort(key=lambda x: x.size_bytes, reverse=True)
        return results

    def _get_dir_size(self, dir_path: str, max_depth: int = 4, current_depth: int = 0) -> Tuple[int, int]:
        """递归计算目录大小。

        Args:
            dir_path: 目录路径。
            max_depth: 最大递归深度。
            current_depth: 当前递归深度。

        Returns:
            (总大小字节, 文件数)
        """
        total_size = 0
        file_count = 0

        if current_depth > max_depth:
            return 0, 0

        if self._cancelled:
            return 0, 0

        try:
            with os.scandir(dir_path) as entries:
                for entry in entries:
                    if self._cancelled:
                        break
                    try:
                        if entry.is_file():
                            total_size += entry.stat().st_size
                            file_count += 1
                        elif entry.is_dir():
                            sub_size, sub_count = self._get_dir_size(
                                entry.path, max_depth, current_depth + 1
                            )
                            total_size += sub_size
                            file_count += sub_count
                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError) as e:
            logger.debug("分析目录大小异常: %s - %s", dir_path, e)

        return total_size, file_count

    def analyze_directory(self, dir_path: str, max_depth: int = 5) -> List[DirSizeInfo]:
        """分析指定目录的子目录大小。

        Args:
            dir_path: 要分析的目录路径。
            max_depth: 最大深度。

        Returns:
            DirSizeInfo 列表，按大小降序排序。
        """
        results = []

        if not os.path.exists(dir_path):
            return results

        try:
            with os.scandir(dir_path) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir():
                            info = DirSizeInfo(
                                path=entry.path,
                                name=entry.name,
                                depth=1,
                            )
                            info.size_bytes, info.file_count = self._get_dir_size(
                                entry.path, max_depth=max_depth
                            )
                            results.append(info)
                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError) as e:
            logger.debug("分析子目录异常: %s - %s", dir_path, e)

        results.sort(key=lambda x: x.size_bytes, reverse=True)
        return results
