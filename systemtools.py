# -*- coding: utf-8 -*-
"""系统管理模块 v3.0

提供软件卸载、启动项管理、注册表残留清理、Windows 任务计划功能。
所有涉及修改系统的操作都要求用户确认，并尽量先备份/可恢复。

安全设计：
- 软件卸载：仅调用程序自带的官方卸载命令（UninstallString），不手动删文件
- 启动项：禁用（重命名注册表值）而非删除，可一键恢复
- 注册表清理：默认仅"列出"无效项，删除需用户二次确认
- 任务计划：使用 Windows 自带 schtasks，不修改注册表
"""

import os
import sys
import time
import logging
import shutil
import subprocess
from typing import List, Dict, Optional
from dataclasses import dataclass, field

from utils import is_file_in_use

logger = logging.getLogger(__name__)

try:
    import winreg
    HAS_WINREG = True
except ImportError:
    HAS_WINREG = False
    logger.warning("当前环境不支持 winreg（非 Windows），系统管理功能受限")


@dataclass
class ProgramInfo:
    """已安装程序信息。"""
    name: str
    publisher: str = ""
    version: str = ""
    uninstall_string: str = ""
    registry_key: str = ""  # 注册表子键路径（用于定位）
    estimated_size_mb: int = 0
    registry_root: str = ""  # HKLM / HKCU


@dataclass
class StartupItem:
    """启动项信息。"""
    name: str
    command: str
    location: str  # 注册表完整路径
    root: int  # winreg.HKEY_* 常量
    value_name: str
    enabled: bool = True


@dataclass
class RegistryResidual:
    """注册表残留项（卸载项指向不存在的文件）。"""
    key_path: str
    value_name: str
    value_data: str


# ======================== 软件卸载 ========================

def get_installed_programs() -> List[ProgramInfo]:
    """读取已安装程序列表（来自注册表 Uninstall 键）。

    Returns:
        已安装程序列表，按名称排序。
    """
    programs: List[ProgramInfo] = []
    if not HAS_WINREG:
        return programs

    uninstall_roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]

    for root, subkey in uninstall_roots:
        try:
            with winreg.OpenKey(root, subkey) as key:
                count = winreg.QueryInfoKey(key)[0]
                for i in range(count):
                    try:
                        prog_key_name = winreg.EnumKey(key, i)
                        with winreg.OpenKey(key, prog_key_name) as prog_key:
                            info = _read_program_info(root, subkey, prog_key_name, prog_key)
                            if info and info.name and info.name != "InstallShield":
                                programs.append(info)
                    except OSError:
                        continue
        except OSError as e:
            logger.debug("读取卸载键失败 %s: %s", subkey, e)

    programs.sort(key=lambda p: p.name.lower())
    return programs


def _read_program_info(self_root, subkey, prog_key_name, prog_key) -> Optional[ProgramInfo]:
    """从注册表键值读取程序信息。"""
    try:
        def _get(name, default=""):
            try:
                return winreg.QueryValueEx(prog_key, name)[0]
            except OSError:
                return default

        name = _get("DisplayName", "")
        if not name:
            return None

        uninstall_str = _get("UninstallString", "")
        publisher = _get("Publisher", "")
        version = _get("DisplayVersion", "")
        size = _get("EstimatedSize", 0)
        try:
            size_mb = int(size) // 1024 if isinstance(size, int) else 0
        except (ValueError, TypeError):
            size_mb = 0

        root_name = "HKLM" if self_root == winreg.HKEY_LOCAL_MACHINE else "HKCU"
        return ProgramInfo(
            name=name,
            publisher=publisher,
            version=version,
            uninstall_string=uninstall_str,
            registry_key=prog_key_name,
            estimated_size_mb=size_mb,
            registry_root=root_name,
        )
    except OSError:
        return None


def uninstall_program(prog: ProgramInfo) -> bool:
    """使用程序自带的官方卸载命令卸载程序。

    仅执行注册表中的 UninstallString，不手动删除文件，安全可控。

    Args:
        prog: ProgramInfo 对象。

    Returns:
        True 表示卸载命令已成功启动。
    """
    if not prog.uninstall_string:
        logger.warning("程序 %s 无可用的卸载命令", prog.name)
        return False

    cmd = prog.uninstall_string.strip()
    # 处理成对的引号命令（如 "C:\x\uninst.exe" /S）
    if cmd.startswith('"') and '"' in cmd[1:]:
        end = cmd.index('"', 1)
        exe = cmd[:end + 1]
        args = cmd[end + 1:].strip()
        cmd_list = [exe]
        if args:
            cmd_list.extend(args.split())
    else:
        cmd_list = cmd.split()

    try:
        logger.info("启动卸载程序: %s | 命令: %s", prog.name, cmd)
        subprocess.Popen(cmd_list, shell=False)
        return True
    except Exception as e:
        logger.error("卸载程序失败 %s: %s", prog.name, e)
        return False


# ======================== 启动项管理 ========================

def get_startup_items() -> List[StartupItem]:
    """获取开机启动项列表。

    Returns:
        启动项列表。
    """
    items: List[StartupItem] = []
    if not HAS_WINREG:
        return items

    startup_keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce"),
    ]

    for root, subkey in startup_keys:
        try:
            with winreg.OpenKey(root, subkey) as key:
                count = winreg.QueryInfoKey(key)[1]
                for i in range(count):
                    try:
                        value_name, value_data, _ = winreg.EnumValue(key, i)
                        items.append(StartupItem(
                            name=value_name,
                            command=str(value_data),
                            location=f"{root_name(root)}\\{subkey}",
                            root=root,
                            value_name=value_name,
                            enabled=True,
                        ))
                    except OSError:
                        continue
        except OSError:
            continue

    return items


def set_startup_enabled(item: StartupItem, enabled: bool) -> bool:
    """启用/禁用启动项。

    通过重命名注册表值实现（禁用时加 "__disabled__" 前缀，可恢复）。

    Args:
        item: 启动项。
        enabled: True 启用，False 禁用。

    Returns:
        True 表示操作成功。
    """
    if not HAS_WINREG:
        return False

    prefix = "__disabled__"
    try:
        with winreg.OpenKey(item.root, item.location.split("\\", 1)[1], 0, winreg.KEY_ALL_ACCESS) as key:
            if enabled:
                # 恢复：从禁用名改回原名
                if item.value_name.startswith(prefix):
                    real_name = item.value_name[len(prefix):]
                    try:
                        data, typ = winreg.QueryValueEx(key, item.value_name)
                        winreg.SetValueEx(key, real_name, 0, typ, data)
                        winreg.DeleteValue(key, item.value_name)
                    except OSError:
                        return False
            else:
                # 禁用：原名为启用状态，重命名为带前缀
                if not item.value_name.startswith(prefix):
                    try:
                        data, typ = winreg.QueryValueEx(key, item.value_name)
                        winreg.SetValueEx(key, prefix + item.value_name, 0, typ, data)
                        winreg.DeleteValue(key, item.value_name)
                    except OSError:
                        return False
        return True
    except OSError as e:
        logger.error("设置启动项失败: %s", e)
        return False


def root_name(root) -> str:
    """返回注册表根的简短名称。"""
    if not HAS_WINREG:
        return "HKEY"
    return "HKLM" if root == winreg.HKEY_LOCAL_MACHINE else "HKCU"


# ======================== 注册表残留清理（谨慎） ========================

def find_registry_residuals() -> List[RegistryResidual]:
    """查找无效卸载项（UninstallString 指向不存在的文件）。

    仅列出，不自动删除。删除需用户二次确认。

    Returns:
        无效卸载项列表。
    """
    residuals: List[RegistryResidual] = []
    if not HAS_WINREG:
        return residuals

    uninstall_roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]

    for root, subkey in uninstall_roots:
        try:
            with winreg.OpenKey(root, subkey) as key:
                count = winreg.QueryInfoKey(key)[0]
                for i in range(count):
                    try:
                        prog_key_name = winreg.EnumKey(key, i)
                        full_path = f"{root_name(root)}\\{subkey}\\{prog_key_name}"
                        with winreg.OpenKey(key, prog_key_name) as prog_key:
                            try:
                                display_name, _ = winreg.QueryValueEx(prog_key, "DisplayName")
                            except OSError:
                                display_name = prog_key_name
                            try:
                                uninstall_str, _ = winreg.QueryValueEx(prog_key, "UninstallString")
                            except OSError:
                                continue
                            # 提取卸载命令中的 exe 路径
                            exe = uninstall_str.strip().strip('"').split('"')[0].split()[0] if uninstall_str else ""
                            if exe and not os.path.exists(exe):
                                residuals.append(RegistryResidual(
                                    key_path=full_path,
                                    value_name="UninstallString",
                                    value_data=uninstall_str,
                                ))
                    except OSError:
                        continue
        except OSError:
            continue

    return residuals


def delete_registry_residual(residual: RegistryResidual) -> bool:
    """删除单个注册表残留项（删除整个卸载子键）。

    危险操作，仅当用户明确确认时调用。

    Args:
        residual: 残留项。

    Returns:
        True 表示删除成功。
    """
    if not HAS_WINREG:
        return False
    try:
        # residual.key_path 形如 HKLM\SOFTWARE\...\Uninstall\{GUID}
        parts = residual.key_path.split("\\")
        root_str = parts[0]
        subkey = "\\".join(parts[1:])
        root = winreg.HKEY_LOCAL_MACHINE if root_str == "HKLM" else winreg.HKEY_CURRENT_USER
        # 删除整个子键
        _delete_registry_tree(root, subkey)
        logger.info("已删除注册表残留项: %s", residual.key_path)
        return True
    except OSError as e:
        logger.error("删除注册表残留失败: %s", e)
        return False


def _delete_registry_tree(root, subkey: str):
    """递归删除注册表子键树。"""
    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                    _delete_registry_tree(root, f"{subkey}\\{child}")
                except OSError:
                    break
        winreg.DeleteKey(root, subkey)
    except OSError:
        # 空键直接删除
        try:
            winreg.DeleteKey(root, subkey)
        except OSError:
            pass


# ======================== Windows 任务计划 ========================

def create_task_scheduler(task_name: str, exe_path: str, interval_hours: int = 24) -> bool:
    """创建 Windows 任务计划程序任务，定期运行清理程序。

    Args:
        task_name: 任务名称。
        exe_path: 要运行的 exe 路径。
        interval_hours: 间隔小时数。

    Returns:
        True 表示创建成功。
    """
    if sys.platform != "win32":
        logger.warning("任务计划仅支持 Windows")
        return False

    try:
        cmd = [
            "schtasks", "/Create",
            "/TN", task_name,
            "/TR", f'"{exe_path}"',
            "/SC", "HOURLY",
            "/MO", str(max(1, interval_hours)),
            "/F",  # 强制覆盖
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            logger.info("任务计划创建成功: %s", task_name)
            return True
        else:
            logger.warning("任务计划创建失败: %s", result.stderr)
            return False
    except Exception as e:
        logger.error("创建任务计划异常: %s", e)
        return False


def remove_task_scheduler(task_name: str) -> bool:
    """删除 Windows 任务计划程序任务。

    Args:
        task_name: 任务名称。

    Returns:
        True 表示删除成功。
    """
    if sys.platform != "win32":
        return False
    try:
        result = subprocess.run(
            ["schtasks", "/Delete", "/TN", task_name, "/F"],
            capture_output=True, text=True, timeout=30,
        )
        logger.info("任务计划删除: %s (rc=%d)", task_name, result.returncode)
        return result.returncode == 0
    except Exception as e:
        logger.error("删除任务计划异常: %s", e)
        return False


def move_file_to_drive(src: str, dest_drive: str) -> tuple:
    """将大文件移动到其他盘（迁移而非删除）。

    Args:
        src: 源文件路径。
        dest_drive: 目标盘符（如 "D:\\"）。

    Returns:
        三元组 (success: bool, new_path: Optional[str], message: str)。
        success 为 True 时 new_path 为迁移后的路径；为 False 时 message 说明原因。
    """
    try:
        if not os.path.exists(src):
            return (False, None, "源文件不存在")
        if not dest_drive or not os.path.isdir(dest_drive):
            return (False, None, f"目标盘符不存在或不可访问：{dest_drive}")
        # 同盘无需迁移
        if os.path.splitdrive(src)[0].lower() == os.path.splitdrive(dest_drive)[0].lower():
            return (False, None, "源文件与目标在同一盘，无需迁移")
        # 文件被占用则无法移动
        if is_file_in_use(src):
            return (False, None, "文件正在被占用，请关闭相关程序后再试")
        dest_dir = os.path.join(dest_drive, "CCleaner_Migrated")
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, os.path.basename(src))
        # 避免目标同名冲突
        if os.path.exists(dest):
            dest = os.path.join(dest_dir, f"{int(time.time())}_{os.path.basename(src)}")
        shutil.move(src, dest)
        logger.info("文件已迁移: %s -> %s", src, dest)
        return (True, dest, "迁移成功")
    except PermissionError:
        return (False, None, "权限不足（请尝试以管理员身份运行）")
    except (OSError, shutil.Error) as e:
        logger.error("文件迁移失败 %s: %s", src, e)
        return (False, None, f"迁移失败：{e}")
