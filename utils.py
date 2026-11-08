# -*- coding: utf-8 -*-
"""工具函数模块

提供磁盘空间查询、文件大小格式化、日志配置等通用功能。
"""

import os
import logging
import shutil
import ctypes
import threading
from typing import Tuple, Optional, List, Dict

# ======================== 日志配置 ========================

def setup_logging(log_file: str = None):
    """配置全局日志，同时输出到文件和控制台。

    Args:
        log_file: 日志文件路径，默认为项目目录下的 cleaner.log。
    """
    if log_file is None:
        log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cleaner.log")

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # 文件处理器：记录 DEBUG 及以上
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)

    # 控制台处理器：记录 INFO 及以上
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_fmt = logging.Formatter(
        "[%(levelname)s] %(message)s",
    )
    console_handler.setFormatter(console_fmt)

    # 避免重复添加处理器
    if not logger.handlers:
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)


# ======================== 磁盘信息 ========================

def get_disk_usage(drive: str = "C:\\") -> Tuple[int, int, int]:
    """获取指定磁盘的使用情况。

    Args:
        drive: 磁盘盘符，如 "C:\\"。

    Returns:
        元组 (总容量字节, 已用空间字节, 可用空间字节)。
        如果获取失败，返回 (0, 0, 0)。
    """
    try:
        total, used, free = shutil.disk_usage(drive)
        return total, used, free
    except (OSError, FileNotFoundError) as e:
        logging.getLogger(__name__).error("获取磁盘 %s 信息失败: %s", drive, e)
        return 0, 0, 0


def get_disk_usage_str(drive: str = "C:\\") -> Tuple[str, str, str]:
    """获取格式化的磁盘使用情况。

    Args:
        drive: 磁盘盘符。

    Returns:
        元组 (总容量字符串, 已用空间字符串, 可用空间字符串)。
    """
    total, used, free = get_disk_usage(drive)
    return format_size(total), format_size(used), format_size(free)


def get_disk_usage_percent(drive: str = "C:\\") -> float:
    """获取磁盘使用率百分比。

    Args:
        drive: 磁盘盘符。

    Returns:
        使用率百分比（0.0 ~ 100.0），失败返回 0.0。
    """
    total, used, _ = get_disk_usage(drive)
    if total == 0:
        return 0.0
    return round(used / total * 100, 1)


# ======================== 文件大小格式化 ========================

def format_size(size_bytes: int) -> str:
    """将字节大小格式化为人类可读的字符串。

    Args:
        size_bytes: 文件大小（字节）。

    Returns:
        格式化字符串，如 "1.23 GB"、"456.78 MB"。
    """
    if size_bytes < 0:
        return "0 B"
    if size_bytes == 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    size = float(size_bytes)

    while size >= 1024.0 and unit_index < len(units) - 1:
        size /= 1024.0
        unit_index += 1

    # 大于 1GB 保留两位小数，否则一位
    if unit_index >= 2:
        return f"{size:.2f} {units[unit_index]}"
    else:
        return f"{size:.1f} {units[unit_index]}"


# ======================== 文件操作工具 ========================

def is_file_in_use(file_path: str) -> bool:
    """检查文件是否正在被其他进程占用。

    通过尝试以独占模式打开文件来判断。

    Args:
        file_path: 文件完整路径。

    Returns:
        True 表示文件被占用，False 表示文件空闲可用。
    """
    if not os.path.exists(file_path):
        return False
    try:
        # Windows 下尝试以独占写入模式打开
        fd = os.open(file_path, os.O_RDWR)
        os.close(fd)
        return False
    except (OSError, IOError):
        return True


# ======================== 回收站 Shell API ========================

# SHQueryRecycleBin 返回结构
class _SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("i64Size", ctypes.c_longlong),
        ("i64NumItems", ctypes.c_longlong),
    ]


def get_recycle_bin_info(drive_root: str = None) -> Tuple[int, int]:
    """通过 Windows Shell API 获取回收站信息。

    使用 SHQueryRecycleBinW 获取指定驱动器或所有驱动器的回收站统计。

    Args:
        drive_root: 驱动器根路径，如 "C:\\\\"，None 表示所有驱动器。

    Returns:
        元组 (文件数量, 总大小字节)。失败返回 (0, 0)。
    """
    try:
        shell32 = ctypes.windll.shell32
        info = _SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(_SHQUERYRBINFO)

        if drive_root is not None:
            result = shell32.SHQueryRecycleBinW(drive_root, ctypes.byref(info))
        else:
            result = shell32.SHQueryRecycleBinW(None, ctypes.byref(info))

        if result == 0:  # S_OK
            return int(info.i64NumItems), int(info.i64Size)
        else:
            logging.getLogger(__name__).debug(
                "SHQueryRecycleBinW 返回错误码: 0x%08X (路径: %s)",
                result,
                drive_root or "所有驱动器",
            )
            return 0, 0
    except (OSError, AttributeError) as e:
        logging.getLogger(__name__).warning("调用回收站 API 失败: %s", e)
        return 0, 0


def empty_recycle_bin(hwnd: int = 0, drive_root: str = None, silent: bool = True) -> bool:
    """通过 Windows Shell API 清空回收站。

    使用 SHEmptyRecycleBinW，正确处理所有驱动器的回收站。

    Args:
        hwnd: 父窗口句柄，0 表示无。
        drive_root: 驱动器根路径，如 "C:\\\\"，None 表示所有驱动器。
        silent: True 表示静默清空（无确认、无进度、无声音）。

    Returns:
        True 表示成功，False 表示失败。
    """
    try:
        shell32 = ctypes.windll.shell32

        # 标志位
        # SHERB_NOCONFIRMATION = 0x00000001  不弹确认对话框
        # SHERB_NOPROGRESSUI   = 0x00000002  不显示进度UI
        # SHERB_NOSOUND        = 0x00000004  不播放声音
        flags = 0x07 if silent else 0x00

        result = shell32.SHEmptyRecycleBinW(hwnd, drive_root, flags)

        if result == 0:  # S_OK
            logging.getLogger(__name__).info(
                "回收站清空成功 (路径: %s)", drive_root or "所有驱动器"
            )
            return True
        else:
            logging.getLogger(__name__).warning(
                "SHEmptyRecycleBinW 返回错误码: 0x%08X (路径: %s)",
                result,
                drive_root or "所有驱动器",
            )
            return False
    except (OSError, AttributeError) as e:
        logging.getLogger(__name__).error("调用清空回收站 API 失败: %s", e)
        return False


def get_all_drives() -> list:
    """获取系统中所有可用驱动器盘符列表。

    Returns:
        驱动器根路径列表，如 ['C:\\\\', 'D:\\\\', ...]。
    """
    drives = []
    # Windows API: GetLogicalDrives 返回位掩码
    try:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for i in range(26):  # A-Z
            if bitmask & (1 << i):
                drive_letter = chr(ord('A') + i)
                drives.append(f"{drive_letter}:\\")
    except (OSError, AttributeError):
        # 回退：至少返回 C 盘
        drives.append("C:\\")
    return drives


def is_process_elevated() -> bool:
    """检查当前进程是否具有管理员权限。

    Returns:
        True 表示以管理员身份运行。
    """
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (OSError, AttributeError):
        return False


def safe_remove_file(file_path: str) -> bool:
    """安全删除单个文件。

    会先检查文件是否被占用，被占用则跳过。

    Args:
        file_path: 文件完整路径。

    Returns:
        True 表示删除成功，False 表示删除失败。
    """
    logger = logging.getLogger(__name__)
    try:
        if not os.path.exists(file_path):
            return False

        # 检查文件是否被占用
        if is_file_in_use(file_path):
            logger.debug("文件被占用，跳过删除: %s", file_path)
            return False

        # 尝试删除，先尝试普通删除，失败则尝试只读删除
        try:
            os.remove(file_path)
        except PermissionError:
            # 去除只读属性后重试
            os.chmod(file_path, 0o777)
            os.remove(file_path)

        logger.debug("成功删除文件: %s", file_path)
        return True
    except (OSError, IOError) as e:
        logger.warning("删除文件失败: %s - %s", file_path, e)
        return False


def safe_remove_dir(dir_path: str) -> Tuple[int, int]:
    """安全删除目录中的所有文件（保留目录本身）。

    Args:
        dir_path: 目录路径。

    Returns:
        元组 (成功删除的文件数, 释放的字节数)。
    """
    logger = logging.getLogger(__name__)
    deleted_count = 0
    freed_size = 0

    if not os.path.exists(dir_path):
        return deleted_count, freed_size

    for root, dirs, files in os.walk(dir_path, topdown=False):
        for filename in files:
            file_path = os.path.join(root, filename)
            try:
                file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
                if safe_remove_file(file_path):
                    deleted_count += 1
                    freed_size += file_size
            except (OSError, IOError) as e:
                logger.warning("处理文件失败: %s - %s", file_path, e)

        # 尝试删除空子目录
        for dirname in dirs:
            dir_full = os.path.join(root, dirname)
            try:
                os.rmdir(dir_full)
            except OSError:
                pass  # 目录非空则保留

    return deleted_count, freed_size


# ======================== 路径工具 ========================

def normalize_path(path: str) -> str:
    """规范化路径，统一大小写和分隔符。

    Args:
        path: 原始路径。

    Returns:
        规范化后的路径（小写）。
    """
    return os.path.normpath(path).lower()


def is_sub_path(child_path: str, parent_path: str) -> bool:
    """检查 child_path 是否是 parent_path 的子路径。

    Args:
        child_path: 子路径。
        parent_path: 父路径。

    Returns:
        True 表示 child_path 在 parent_path 下。
    """
    child = normalize_path(child_path)
    parent = normalize_path(parent_path)
    # 确保父路径以分隔符结尾，避免误匹配
    if not parent.endswith(os.sep):
        parent = parent + os.sep
    return child.startswith(parent)


# ======================= 大文件查找 =======================

def find_large_files(
    scan_path: str = "C:\\",
    min_size_mb: int = 1024,
    max_depth: int = 10,
    current_depth: int = 0,
    cancel_event: Optional[threading.Event] = None,
) -> List[Tuple[str, int]]:
    """查找指定路径下的大文件（> min_size_mb MB）。

    Args:
        scan_path: 要扫描的路径。
        min_size_mb: 最小文件大小（MB），默认 1024MB = 1GB。
        max_depth: 最大递归深度。
        current_depth: 当前递归深度。
        cancel_event: 取消事件。

    Returns:
        列表 [(文件路径, 文件大小字节)]，按大小降序排序。
    """
    results = []
    min_size_bytes = min_size_mb * 1024 * 1024

    if not os.path.exists(scan_path):
        return results

    if current_depth > max_depth:
        return results

    if cancel_event and cancel_event.is_set():
        return results

    try:
        with os.scandir(scan_path) as entries:
            for entry in entries:
                if cancel_event and cancel_event.is_set():
                    break

                try:
                    if entry.is_file():
                        if entry.stat().st_size >= min_size_bytes:
                            results.append((entry.path, entry.stat().st_size))
                    elif entry.is_dir():
                        sub_results = find_large_files(
                            entry.path, min_size_mb, max_depth,
                            current_depth + 1, cancel_event
                        )
                        results.extend(sub_results)
                except (OSError, PermissionError):
                    continue
    except (OSError, PermissionError):
        pass

    # 按大小降序排序
    results.sort(key=lambda x: x[1], reverse=True)
    return results


# ======================= 重复文件查找 =======================

def find_duplicate_files(
    scan_paths: List[str],
    min_size_mb: int = 1,
    cancel_event: Optional[threading.Event] = None,
) -> Dict[str, List[str]]:
    """查找重复文件（基于文件大小和 MD5 哈希）。

    Args:
        scan_paths: 要扫描的路径列表。
        min_size_mb: 最小文件大小（MB），小于此大小的文件不检查。
        cancel_event: 取消事件。

    Returns:
        字典 {文件哈希: [文件路径列表]}，仅包含重复文件（列表长度 > 1）。
    """
    import hashlib

    min_size_bytes = min_size_mb * 1024 * 1024

    # 第一阶段：按大小分组
    size_groups: Dict[int, List[str]] = {}

    for scan_path in scan_paths:
        if cancel_event and cancel_event.is_set():
            break
        if not os.path.exists(scan_path):
            continue

        try:
            for root, dirs, files in os.walk(scan_path):
                if cancel_event and cancel_event.is_set():
                    break
                for filename in files:
                    if cancel_event and cancel_event.is_set():
                        break
                    file_path = os.path.join(root, filename)
                    try:
                        size = os.path.getsize(file_path)
                        if size >= min_size_bytes:
                            if size not in size_groups:
                                size_groups[size] = []
                            size_groups[size].append(file_path)
                    except OSError:
                        continue
        except OSError:
            continue

    # 第二阶段：对大小相同的文件计算 MD5
    hash_groups: Dict[str, List[str]] = {}

    for size, files in size_groups.items():
        if len(files) < 2:
            continue  # 大小唯一的文件不可能是重复文件
        if cancel_event and cancel_event.is_set():
            break

        for file_path in files:
            if cancel_event and cancel_event.is_set():
                break
            try:
                file_hash = _calc_file_md5(file_path)
                if file_hash:
                    if file_hash not in hash_groups:
                        hash_groups[file_hash] = []
                    hash_groups[file_hash].append(file_path)
            except OSError:
                continue

    # 仅返回重复文件（哈希组长度 > 1）
    return {h: paths for h, paths in hash_groups.items() if len(paths) > 1}


def _calc_file_md5(file_path: str, chunk_size: int = 8192) -> Optional[str]:
    """计算文件的 MD5 哈希值。

    Args:
        file_path: 文件路径。
        chunk_size: 读取块大小（字节）。

    Returns:
        MD5 哈希值（十六进制字符串），失败返回 None。
    """
    import hashlib

    try:
        md5_hash = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                md5_hash.update(chunk)
        return md5_hash.hexdigest()
    except OSError:
        return None

