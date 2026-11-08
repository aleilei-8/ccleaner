# -*- coding: utf-8 -*-
"""配置管理模块 v3.0

定义所有清理类别、保护规则和自动清理设置。
所有路径和规则集中管理，便于维护和扩展。

v3.0 更新：
- 每个类别新增 clean_target（files 逐个删 / dir 整目录删 / shell 回收站）
- 每个类别新增 scan_mode（deep 深度递归 / shallow 仅一层）
- 路径改用环境变量（%SystemRoot%、%TEMP%、%LOCALAPPDATA% 等），扫描时展开
- 新增软件卸载 / 启动项 / 注册表 / 大文件 / 重复文件 等功能的配置键
"""

import os
import sys
import json
import logging
from typing import Dict, List, Set

logger = logging.getLogger(__name__)


def _get_app_dir() -> str:
    """获取应用程序数据目录（兼容 PyInstaller --onefile）。

    PyInstaller 打包后 __file__ 指向临时解压目录（运行时变化），
    必须使用 sys.executable 所在目录。
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


# ======================== 清理类别定义 ========================

def get_default_categories() -> Dict[str, Dict]:
    """获取默认的清理类别配置。

    返回字典格式:
    {
        "category_name": {
            "paths": [路径列表, 支持 %VAR% 环境变量],
            "description": "类别描述",
            "extensions": [扩展名列表, 可选],
            "use_shell_api": "api名称, 可选",
            "clean_target": "files | dir | shell",  # 清理目标
            "scan_mode": "deep | shallow",          # 扫描模式
            "tab": "quick | deep",                   # 所属 Tab 页
            "default_enabled": true/false,           # 默认是否勾选（风险类默认关）
        }
    }

    clean_target 说明：
    - "dir"：整目录删除（rmtree 后重建空目录），用于明确是"缓存根目录"的类别，最彻底
    - "files"：按扩展名过滤后逐个删文件，用于缓存与目标共享父目录（如 Explorer 缩略图）
    - "shell"：调用 Windows Shell API（回收站）
    """
    return {
        # ====================== 快速清理（常用、安全）======================
        "Windows 临时文件": {
            "paths": ["%SystemRoot%\\Temp", "%TEMP%"],
            "description": "系统和用户运行产生的临时文件，可安全清理（整目录清空）",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "quick",
            "default_enabled": True,
        },
        "回收站": {
            "paths": ["%SystemDrive%\\$Recycle.Bin"],
            "description": "已删除但尚未永久删除的文件（清空所有驱动器）",
            "use_shell_api": "recycle_bin",
            "clean_target": "shell",
            "tab": "quick",
            "default_enabled": True,
        },
        "Chrome 浏览器缓存": {
            "paths": [
                "%LOCALAPPDATA%\\Google\\Chrome\\User Data\\Default\\Cache",
                "%LOCALAPPDATA%\\Google\\Chrome\\User Data\\Default\\Code Cache",
                "%LOCALAPPDATA%\\Google\\Chrome\\User Data\\Default\\Service Worker\\CacheStorage",
            ],
            "description": "Google Chrome 浏览器缓存数据（整目录清理）",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "quick",
            "default_enabled": True,
        },
        "Edge 浏览器缓存": {
            "paths": [
                "%LOCALAPPDATA%\\Microsoft\\Edge\\User Data\\Default\\Cache",
                "%LOCALAPPDATA%\\Microsoft\\Edge\\User Data\\Default\\Code Cache",
                "%LOCALAPPDATA%\\Microsoft\\Edge\\User Data\\Default\\Service Worker\\CacheStorage",
            ],
            "description": "Microsoft Edge 浏览器缓存数据（整目录清理）",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "quick",
            "default_enabled": True,
        },
        "Firefox 浏览器缓存": {
            "paths": ["%LOCALAPPDATA%\\Mozilla\\Firefox\\Profiles"],
            "description": "Firefox 浏览器缓存数据（按缓存扩展名清理）",
            "extensions": [".cache", ".sqlite-wal", ".sqlite-shm"],
            "clean_target": "files",
            "scan_mode": "deep",
            "tab": "quick",
            "default_enabled": True,
        },
        "Windows 更新缓存": {
            "paths": ["%SystemRoot%\\SoftwareDistribution\\Download"],
            "description": "Windows 更新下载的安装包，清理后不影响已安装的更新",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "quick",
            "default_enabled": True,
        },
        "预读取文件": {
            "paths": ["%SystemRoot%\\Prefetch"],
            "description": "Windows 预读取缓存，清理后会自动重建",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "quick",
            "default_enabled": True,
        },
        "缩略图缓存": {
            "paths": ["%LOCALAPPDATA%\\Microsoft\\Windows\\Explorer"],
            "description": "文件缩略图缓存（仅删 thumbcache_*.db，保留其他文件）",
            "extensions": ["thumbcache_*.db"],
            "clean_target": "files",
            "scan_mode": "shallow",
            "tab": "quick",
            "default_enabled": True,
        },
        "Windows 错误报告": {
            "paths": [
                "%ProgramData%\\Microsoft\\Windows\\WER",
                "%LOCALAPPDATA%\\Microsoft\\Windows\\WER",
            ],
            "description": "Windows 错误报告存档，可安全清理",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "quick",
            "default_enabled": True,
        },
        "DirectX 着色器缓存": {
            "paths": ["%LOCALAPPDATA%\\D3DSCache"],
            "description": "DirectX 着色器编译缓存，清理后游戏/应用会重新编译",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "quick",
            "default_enabled": True,
        },
        "传递优化文件": {
            "paths": ["%SystemRoot%\\SoftwareDistribution\\DeliveryOptimization"],
            "description": "传递优化缓存，用于局域网分发 Windows 更新",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "quick",
            "default_enabled": True,
        },

        # ====================== 深度清理（应用缓存）======================
        "Windows 日志文件": {
            "paths": ["%SystemRoot%\\Logs", "%SystemRoot%\\Debug", "%SystemDrive%\\inetpub\\logs"],
            "description": "Windows 系统和应用日志文件（.log, .etl, .txt），清理旧日志",
            "extensions": [".log", ".etl", ".txt"],
            "clean_target": "files",
            "scan_mode": "deep",
            "tab": "deep",
            "default_enabled": True,
        },
        "内存转储文件": {
            "paths": ["%SystemRoot%\\memory.dmp", "%SystemRoot%\\Minidump"],
            "description": "系统崩溃内存转储文件，清理后不影响系统运行",
            "extensions": [".dmp", ".mdmp"],
            "clean_target": "files",
            "scan_mode": "deep",
            "tab": "deep",
            "default_enabled": True,
        },
        "Windows 升级残留": {
            "paths": ["%SystemRoot%.~BT", "%SystemRoot%.~LS",
                      "%SystemDrive%\\$WINDOWS.~BT", "%SystemDrive%\\$WINDOWS.~LS"],
            "description": "Windows 升级残留的临时文件，升级完成后可安全删除",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "deep",
            "default_enabled": True,
        },
        "Windows 应用商店缓存": {
            "paths": [
                "%LOCALAPPDATA%\\Packages\\Microsoft.WindowsStore_8wekyb3d8bbwe\\LocalCache",
                "%LOCALAPPDATA%\\Packages\\Microsoft.WindowsStore_8wekyb3d8bbwe\\LocalState",
            ],
            "description": "Microsoft Store 应用商店缓存数据",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "deep",
            "default_enabled": True,
        },
        "系统通知缓存": {
            "paths": ["%LOCALAPPDATA%\\Microsoft\\Windows\\Notifications"],
            "description": "Windows 通知历史缓存，清理后不影响系统",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "deep",
            "default_enabled": True,
        },
        "微信 PC 缓存": {
            "paths": ["%USERPROFILE%\\Documents\\WeChat Files"],
            "description": "微信 PC 版临时缓存文件（仅删 .tmp/.cache，默认不勾选以防误删聊天文件）",
            "extensions": [".tmp", ".cache", ".temp", ".log"],
            "clean_target": "files",
            "scan_mode": "deep",
            "tab": "deep",
            "default_enabled": False,
        },
        "QQ 缓存": {
            "paths": ["%USERPROFILE%\\Documents\\Tencent Files"],
            "description": "QQ 接收的文件缓存（仅删 .tmp/.cache，默认不勾选）",
            "extensions": [".tmp", ".cache", ".temp"],
            "clean_target": "files",
            "scan_mode": "deep",
            "tab": "deep",
            "default_enabled": False,
        },
        "Office 最近文档缓存": {
            "paths": [
                "%LOCALAPPDATA%\\Microsoft\\Office\\Recent",
                "%LOCALAPPDATA%\\Microsoft\\Office\\16.0\\Overview",
            ],
            "description": "Microsoft Office 最近打开的文档缓存",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "deep",
            "default_enabled": True,
        },
        "OneDrive 缓存": {
            "paths": [
                "%LOCALAPPDATA%\\Microsoft\\OneDrive\\cache",
                "%LOCALAPPDATA%\\Microsoft\\OneDrive\\logs",
            ],
            "description": "OneDrive 同步缓存和日志文件",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "deep",
            "default_enabled": True,
        },
        "Steam 游戏缓存": {
            "paths": [
                "%ProgramFiles(x86)%\\Steam\\appcache",
                "%ProgramFiles(x86)%\\Steam\\config",
                "%LOCALAPPDATA%\\Steam\\htmlcache",
            ],
            "description": "Steam 游戏平台缓存和配置临时文件",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "deep",
            "default_enabled": True,
        },
        "Discord 缓存": {
            "paths": ["%APPDATA%\\discord\\Cache", "%APPDATA%\\discord\\Code Cache"],
            "description": "Discord 聊天应用缓存数据",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "deep",
            "default_enabled": True,
        },
        "剪映缓存": {
            "paths": [
                "%LOCALAPPDATA%\\JianyingPro\\Cache",
                "%LOCALAPPDATA%\\JianyingPro\\User Data\\Cache",
            ],
            "description": "剪映视频编辑软件缓存文件",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "deep",
            "default_enabled": True,
        },
        "迅雷下载缓存": {
            "paths": [
                "%LOCALAPPDATA%\\Thunder Network\\XLLiveUD\\cache",
                "%LOCALAPPDATA%\\Thunder Network\\ThunderOSP\\cache",
            ],
            "description": "迅雷下载工具缓存文件",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "deep",
            "default_enabled": True,
        },
        "WPS 缓存": {
            "paths": [
                "%LOCALAPPDATA%\\Kingsoft\\WPS Office\\temp",
                "%LOCALAPPDATA%\\Kingsoft\\WPS Office\\update",
            ],
            "description": "WPS Office 临时文件和更新缓存",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "deep",
            "default_enabled": True,
        },
        "PotPlayer 缓存": {
            "paths": ["%LOCALAPPDATA%\\Daum\\PotPlayer\\Cache"],
            "description": "PotPlayer 视频播放器缓存文件",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "deep",
            "default_enabled": True,
        },
        "钉钉缓存": {
            "paths": ["%LOCALAPPDATA%\\DingTalk\\Cache", "%APPDATA%\\DingTalk\\Cache"],
            "description": "钉钉办公应用缓存数据",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "deep",
            "default_enabled": True,
        },

        # ====================== 深度清理（开发环境缓存）======================
        "pip 缓存": {
            "paths": ["%USERPROFILE%\\.cache\\pip", "%LOCALAPPDATA%\\pip\\cache"],
            "description": "Python pip 包管理工具下载缓存",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "deep",
            "default_enabled": True,
        },
        "npm 缓存": {
            "paths": ["%LOCALAPPDATA%\\npm-cache"],
            "description": "Node.js npm 包管理工具缓存",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "deep",
            "default_enabled": True,
        },
        "yarn 缓存": {
            "paths": ["%LOCALAPPDATA%\\Yarn\\cache"],
            "description": "Yarn 包管理工具缓存",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "deep",
            "default_enabled": True,
        },
        "Maven 失败下载残留": {
            "paths": ["%USERPROFILE%\\.m2\\repository"],
            "description": "Maven 构建工具失败下载的 .lastUpdated 文件",
            "extensions": [".lastUpdated"],
            "clean_target": "files",
            "scan_mode": "deep",
            "tab": "deep",
            "default_enabled": True,
        },
        "Gradle 缓存": {
            "paths": ["%USERPROFILE%\\.gradle\\caches"],
            "description": "Gradle 构建工具编译缓存",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "deep",
            "default_enabled": True,
        },
        "conda 缓存": {
            "paths": ["%USERPROFILE%\\.conda\\pkgs"],
            "description": "Conda 环境管理工具包缓存",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "deep",
            "default_enabled": True,
        },
        "VS Code 扩展缓存": {
            "paths": ["%LOCALAPPDATA%\\Code\\Cache", "%LOCALAPPDATA%\\Code\\CachedData"],
            "description": "VS Code 编辑器扩展缓存",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "deep",
            "default_enabled": True,
        },
        "Docker 镜像缓存": {
            "paths": ["%ProgramData%\\Docker\\windowsfilter", "%ProgramData%\\Docker\\tmp"],
            "description": "Docker 容器镜像缓存（需 Docker Desktop 已安装）",
            "clean_target": "dir",
            "scan_mode": "deep",
            "tab": "deep",
            "default_enabled": True,
        },

        # ====================== 命令式系统级清理（需管理员）======================
        "WinSxS 组件存储清理": {
            "description": "Windows 组件存储（WinSxS）中已被取代的旧版本，清理后通常释放数 GB（等同磁盘清理的『Windows 更新清理』），安全。需管理员。",
            "clean_target": "command",
            "command": "Dism.exe /Online /Cleanup-Image /StartComponentCleanup",
            "analyze_command": "Dism.exe /Online /Cleanup-Image /AnalyzeComponentStore",
            "analyze_parser": "dism_reclaim",
            "requires_admin": True,
            "risk_level": "low",
            "tab": "deep",
            "default_enabled": True,
        },
        "系统还原点清理": {
            "description": "删除所有系统还原点/卷影副本（可释放大量空间，但会失去系统还原能力）。需管理员，默认关闭。",
            "clean_target": "command",
            "command": "vssadmin delete shadows /for=C: /all /quiet",
            "requires_admin": True,
            "risk_level": "high",
            "tab": "deep",
            "default_enabled": False,
        },
        "休眠文件清理 (hiberfil.sys)": {
            "description": "关闭休眠并删除 hiberfil.sys（大小约 = 内存容量）。关闭后无法使用休眠功能。需管理员，默认关闭。",
            "clean_target": "command",
            "command": "powercfg -h off",
            "estimate_ram": True,
            "requires_admin": True,
            "risk_level": "high",
            "tab": "deep",
            "default_enabled": False,
        },
        "Windows.old 升级残留": {
            "description": "系统升级后留下的 Windows.old 文件夹，通常数 GB 到数十 GB。仅升级后存在，删除不可撤销。需管理员，默认关闭。",
            "clean_target": "command",
            "command": 'cmd.exe /c "takeown /f C:\\Windows.old /r /d y >nul && rd /s /q C:\\Windows.old"',
            "requires_admin": True,
            "risk_level": "high",
            "tab": "deep",
            "default_enabled": False,
        },

        # ====================== 更多浏览器缓存 ======================
        "Brave 浏览器缓存": {
            "paths": [
                "%LOCALAPPDATA%\\BraveSoftware\\Brave-Browser\\User Data\\Default\\Cache",
                "%LOCALAPPDATA%\\BraveSoftware\\Brave-Browser\\User Data\\Default\\Code Cache",
                "%LOCALAPPDATA%\\BraveSoftware\\Brave-Browser\\User Data\\Default\\Service Worker\\CacheStorage",
            ],
            "description": "Brave 浏览器缓存数据（整目录清理）",
            "clean_target": "dir", "scan_mode": "deep", "tab": "deep", "default_enabled": True,
        },
        "Opera 浏览器缓存": {
            "paths": [
                "%LOCALAPPDATA%\\Opera Software\\Opera Stable\\Cache",
                "%LOCALAPPDATA%\\Opera Software\\Opera Stable\\Code Cache",
            ],
            "description": "Opera 浏览器缓存数据（整目录清理）",
            "clean_target": "dir", "scan_mode": "deep", "tab": "deep", "default_enabled": True,
        },
        "Vivaldi 浏览器缓存": {
            "paths": [
                "%LOCALAPPDATA%\\Vivaldi\\User Data\\Default\\Cache",
                "%LOCALAPPDATA%\\Vivaldi\\User Data\\Default\\Code Cache",
            ],
            "description": "Vivaldi 浏览器缓存数据（整目录清理）",
            "clean_target": "dir", "scan_mode": "deep", "tab": "deep", "default_enabled": True,
        },
        "Yandex 浏览器缓存": {
            "paths": [
                "%LOCALAPPDATA%\\Yandex\\YandexBrowser\\User Data\\Default\\Cache",
                "%LOCALAPPDATA%\\Yandex\\YandexBrowser\\User Data\\Default\\Code Cache",
            ],
            "description": "Yandex 浏览器缓存数据（整目录清理）",
            "clean_target": "dir", "scan_mode": "deep", "tab": "deep", "default_enabled": True,
        },

        # ====================== 开发环境缓存（更多）======================
        "Node npm/yarn/pnpm 缓存": {
            "paths": [
                "%LOCALAPPDATA%\\npm-cache",
                "%APPDATA%\\npm",
                "%LOCALAPPDATA%\\pnpm\\store",
                "%USERPROFILE%\\.yarn\\cache",
            ],
            "description": "Node.js 生态包管理器缓存（npm/yarn/pnpm）",
            "clean_target": "dir", "scan_mode": "deep", "tab": "deep", "default_enabled": True,
        },
        ".NET NuGet 缓存": {
            "paths": [
                "%USERPROFILE%\\.nuget\\packages",
                "%LOCALAPPDATA%\\NuGet\\v3-cache",
                "%TEMP%\\NuGetScratch",
            ],
            "description": "NuGet 包管理工具下载缓存",
            "clean_target": "dir", "scan_mode": "deep", "tab": "deep", "default_enabled": True,
        },
        "Go 模块缓存": {
            "paths": [
                "%LOCALAPPDATA%\\go-build",
                "%USERPROFILE%\\go\\pkg\\mod",
            ],
            "description": "Go 语言模块构建缓存",
            "clean_target": "dir", "scan_mode": "deep", "tab": "deep", "default_enabled": True,
        },
        "Rust Cargo 缓存": {
            "paths": [
                "%USERPROFILE%\\.cargo\\registry",
                "%USERPROFILE%\\.cargo\\git",
            ],
            "description": "Rust Cargo 包注册表缓存",
            "clean_target": "dir", "scan_mode": "deep", "tab": "deep", "default_enabled": True,
        },
        "Python 编译缓存清扫": {
            "paths": ["%LOCALAPPDATA%", "%USERPROFILE%\\.cache"],
            "extensions": [".pyc"],
            "description": "Python 编译缓存文件（.pyc），清理后自动重建，安全",
            "clean_target": "files", "scan_mode": "sweep", "tab": "deep", "default_enabled": True,
            "sweep_skip_user_dirs": True, "sweep_max_depth": 6,
        },
        "Android SDK 缓存": {
            "paths": [
                "%LOCALAPPDATA%\\Android\\Sdk\\.temp",
                "%LOCALAPPDATA%\\Android\\Sdk\\temp",
            ],
            "description": "Android SDK 下载与构建临时文件",
            "clean_target": "dir", "scan_mode": "deep", "tab": "deep", "default_enabled": True,
        },

        # ====================== 应用缓存（更多）======================
        "NVIDIA/AMD 着色器缓存": {
            "paths": [
                "%LOCALAPPDATA%\\NVIDIA\\GLCache",
                "%LOCALAPPDATA%\\NVIDIA\\DXCache",
                "%LOCALAPPDATA%\\AMD\\GLCache",
            ],
            "description": "显卡驱动着色器编译缓存，清理后游戏/应用重新编译（可释放数 GB）",
            "clean_target": "dir", "scan_mode": "deep", "tab": "deep", "default_enabled": True,
        },
        "Microsoft Teams 缓存": {
            "paths": [
                "%APPDATA%\\Microsoft\\Teams\\Cache",
                "%APPDATA%\\Microsoft\\Teams\\Service Worker\\CacheStorage",
                "%APPDATA%\\Microsoft\\Teams\\IndexedDB",
            ],
            "description": "Teams 会议应用缓存数据",
            "clean_target": "dir", "scan_mode": "deep", "tab": "deep", "default_enabled": True,
        },
        "Spotify 缓存": {
            "paths": [
                "%LOCALAPPDATA%\\Spotify\\Data",
                "%LOCALAPPDATA%\\Spotify\\Storage",
            ],
            "description": "Spotify 音乐流媒体缓存",
            "clean_target": "dir", "scan_mode": "deep", "tab": "deep", "default_enabled": True,
        },
        "Adobe 媒体缓存": {
            "paths": [
                "%LOCALAPPDATA%\\Adobe\\Common\\Media Cache",
                "%LOCALAPPDATA%\\Adobe\\Common\\Media Cache Files",
            ],
            "description": "Adobe Premiere/After Effects 媒体缓存（数 GB 常见）",
            "clean_target": "dir", "scan_mode": "deep", "tab": "deep", "default_enabled": True,
        },
        "Zoom 缓存": {
            "paths": [
                "%APPDATA%\\Zoom\\data",
                "%LOCALAPPDATA%\\Zoom\\cache",
            ],
            "description": "Zoom 视频会议缓存",
            "clean_target": "dir", "scan_mode": "deep", "tab": "deep", "default_enabled": True,
        },
        "百度网盘缓存": {
            "paths": [
                "%LOCALAPPDATA%\\baidu\\BaiduNetdisk\\cache",
                "%LOCALAPPDATA%\\baidu\\BaiduYunKernel\\cache",
            ],
            "description": "百度网盘下载/上传临时缓存（默认不勾选，以防误删正在传输的文件）",
            "clean_target": "dir", "scan_mode": "deep", "tab": "deep", "default_enabled": False,
        },
        "游戏平台缓存 (Epic/Battle.net/EA)": {
            "paths": [
                "%PROGRAMDATA%\\Epic\\EpicGamesLauncher\\Cache",
                "%PROGRAMDATA%\\Battle.net\\Cache",
                "%LOCALAPPDATA%\\EADesktop\\Cache",
            ],
            "description": "游戏平台启动器缓存",
            "clean_target": "dir", "scan_mode": "deep", "tab": "deep", "default_enabled": True,
        },

        # ====================== 全盘残留临时文件清扫 ======================
        "用户残留临时文件清扫": {
            "paths": ["%LOCALAPPDATA%", "%TEMP%", "%USERPROFILE%\\AppData"],
            "extensions": [".tmp", ".bak", ".old", ".temp", ".cache", ".chk", ".gid", "thumbs.db", "~*.tmp"],
            "description": "全盘扫描用户目录下的残留临时/备份文件（.tmp/.bak/.old 等），自动跳过系统与个人文档目录，安全",
            "clean_target": "files", "scan_mode": "sweep", "tab": "deep", "default_enabled": True,
            "sweep_skip_user_dirs": True, "sweep_max_depth": 6,
        },
        "系统日志与调试残留": {
            "paths": ["%SystemRoot%\\Logs", "%SystemRoot%\\Debug", "%SystemRoot%\\Temp", "%SystemRoot%\\inf"],
            "extensions": [".log", ".etl", ".old", ".bak", ".tmp", ".txt"],
            "description": "Windows 系统日志、调试与临时残留文件（按扩展名清理）",
            "clean_target": "files", "scan_mode": "sweep", "tab": "deep", "default_enabled": True,
            "sweep_max_depth": 4,
        },
    }


# ======================== 保护规则定义 ========================

def get_protected_directories() -> Set[str]:
    """获取受保护的目录列表，这些目录中的文件永远不会被删除。

    v3.0：保留 v2.0 的全部保护目录（23 个），并补充 ProgramData 关键子目录。
    """
    dirs = {
        r"C:\Windows\System32",
        r"C:\Windows\SysWOW64",
        r"C:\Program Files",
        r"C:\Program Files (x86)",
        r"C:\ProgramData",
        r"C:\Windows\Installer",
        r"C:\Windows\WinSxS",
        r"C:\Windows\assembly",
        r"C:\Windows\Registration",
        # v2.0 新增
        r"C:\Windows\systemresources",
        r"C:\Windows\Boot",
        r"C:\Windows\Panther",
        r"C:\Windows\Policies",
        r"C:\Windows\Help",
        r"C:\Windows\zh-CN",
        r"C:\Windows\en-US",
        r"C:\Windows\Globalization",
        r"C:\Windows\Microsoft.NET",
        r"C:\Windows\ImmersiveControlPanel",
        r"C:\$Recycle.Bin",
        r"C:\System Volume Information",
        r"C:\Recovery",
        r"C:\EFI",
    }
    return {os.path.normpath(d).lower() for d in dirs}


def get_protected_user_dirs() -> List[str]:
    """获取受保护的用户文档目录名称。"""
    return [
        "Documents", "Desktop", "Pictures", "Videos", "Music",
        "Downloads", "Favorites", "Contacts", "Links", "Saved Games",
        "3D Objects", "OneDrive", "Searches", "Tracing",
    ]


def get_protected_extensions_in_windows() -> Set[str]:
    """在 Windows 目录下受保护的文件扩展名（小写）。"""
    return {
        ".dll", ".sys", ".exe", ".drv", ".inf", ".cat", ".msi", ".cab",
        ".nls", ".mui", ".dat", ".reg", ".pol", ".ini", ".xml", ".log",
        ".wim", ".esd", ".mum", ".mof", ".mfl", ".nlp", ".cpl", ".ocx",
        ".shd", ".spl", ".evtx", ".blf", ".regtrans-ms",
    }


def get_protected_files() -> Set[str]:
    """获取绝对不能删除的系统关键文件（小写规范化）。"""
    files = {
        r"C:\bootmgr", r"C:\bootmgr.efi", r"C:\BCD",
        r"C:\Windows\System32\config\SYSTEM",
        r"C:\Windows\System32\config\SOFTWARE",
        r"C:\Windows\System32\config\SAM",
        r"C:\Windows\System32\config\SECURITY",
        r"C:\Windows\System32\config\DEFAULT",
        r"C:\Windows\System32\ntoskrnl.exe",
        r"C:\Windows\System32\hal.dll",
        r"C:\Windows\System32\winload.exe",
        r"C:\Windows\System32\winload.efi",
        r"C:\Windows\System32\ci.dll",
        r"C:\Windows\System32\clfs.sys",
        r"C:\Windows\System32\mcupdate_GenuineIntel.dll",
        r"C:\Windows\System32\pshed.dll",
        r"C:\Windows\System32\bootwin.exe",
        r"C:\Windows\Boot\PCAT\bootmgr.exe",
        r"C:\Windows\Boot\PCAT\bootmgr.efi",
    }
    return {os.path.normpath(f).lower() for f in files}


def get_protected_system_files_pattern() -> List[str]:
    """受保护系统文件的文件名模式（通配符）。"""
    return [
        "pagefile.sys", "swapfile.sys", "hiberfil.sys",
        "dumpstack.log", "MEMORY.DMP", "*.DMP",
    ]


# ======================== 配置持久化 ========================

class Config:
    """配置管理类，负责加载和保存用户偏好设置。

    v3.0 新增：large_file_threshold、protect_large_files（大文件保护）、
    system_management（系统管理模块开关）等。
    """

    DEFAULT_CONFIG_FILE = os.path.join(_get_app_dir(), "cleaner_config.json")

    def __init__(self, config_file: str = None):
        self.config_file = config_file or self.DEFAULT_CONFIG_FILE
        self._data: Dict = {}
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            else:
                self._data = self._default_config()
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("加载配置文件失败: %s，使用默认配置", e)
            self._data = self._default_config()

    def _default_config(self) -> Dict:
        return {
            "auto_clean": False,
            "auto_clean_interval_hours": 24,
            "selected_categories": [],
            "window_geometry": None,
            "theme": "dark",
            "minimize_to_tray": True,
            "deep_clean": False,
            "large_file_threshold_mb": 1024,
            "protect_large_files": True,
            "dry_run_default": False,
            "use_quarantine": True,
            "scan_threads": 4,
            "enable_system_management": False,
            "use_task_scheduler": False,
        }

    def save(self):
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            logger.info("配置文件保存成功")
        except IOError as e:
            logger.error("保存配置文件失败: %s", e)

    @property
    def auto_clean(self) -> bool:
        return self._data.get("auto_clean", False)

    @auto_clean.setter
    def auto_clean(self, value: bool):
        self._data["auto_clean"] = value
        self.save()

    @property
    def auto_clean_interval_hours(self) -> int:
        return self._data.get("auto_clean_interval_hours", 24)

    @auto_clean_interval_hours.setter
    def auto_clean_interval_hours(self, value: int):
        self._data["auto_clean_interval_hours"] = value
        self.save()

    @property
    def selected_categories(self) -> List[str]:
        return self._data.get("selected_categories", [])

    @selected_categories.setter
    def selected_categories(self, value: List[str]):
        self._data["selected_categories"] = value
        self.save()

    @property
    def window_geometry(self) -> str:
        return self._data.get("window_geometry", "")

    @window_geometry.setter
    def window_geometry(self, value: str):
        self._data["window_geometry"] = value
        self.save()

    @property
    def theme(self) -> str:
        return self._data.get("theme", "dark")

    @theme.setter
    def theme(self, value: str):
        self._data["theme"] = value
        self.save()

    @property
    def minimize_to_tray(self) -> bool:
        return self._data.get("minimize_to_tray", True)

    @minimize_to_tray.setter
    def minimize_to_tray(self, value: bool):
        self._data["minimize_to_tray"] = value
        self.save()

    # v3.0 配置项
    @property
    def deep_clean(self) -> bool:
        return self._data.get("deep_clean", False)

    @deep_clean.setter
    def deep_clean(self, value: bool):
        self._data["deep_clean"] = value
        self.save()

    @property
    def large_file_threshold_mb(self) -> int:
        return self._data.get("large_file_threshold_mb", 1024)

    @large_file_threshold_mb.setter
    def large_file_threshold_mb(self, value: int):
        self._data["large_file_threshold_mb"] = value
        self.save()

    @property
    def protect_large_files(self) -> bool:
        return self._data.get("protect_large_files", True)

    @protect_large_files.setter
    def protect_large_files(self, value: bool):
        self._data["protect_large_files"] = value
        self.save()

    @property
    def dry_run_default(self) -> bool:
        return self._data.get("dry_run_default", False)

    @dry_run_default.setter
    def dry_run_default(self, value: bool):
        self._data["dry_run_default"] = value
        self.save()

    @property
    def use_quarantine(self) -> bool:
        """隔离模式：删除默认移入隔离区（可一键恢复），关闭则永久删除。"""
        return self._data.get("use_quarantine", True)

    @use_quarantine.setter
    def use_quarantine(self, value: bool):
        self._data["use_quarantine"] = value
        self.save()

    @property
    def scan_threads(self) -> int:
        return self._data.get("scan_threads", 4)

    @scan_threads.setter
    def scan_threads(self, value: int):
        self._data["scan_threads"] = max(1, min(value, 16))
        self.save()

    @property
    def enable_system_management(self) -> bool:
        return self._data.get("enable_system_management", False)

    @enable_system_management.setter
    def enable_system_management(self, value: bool):
        self._data["enable_system_management"] = value
        self.save()

    @property
    def use_task_scheduler(self) -> bool:
        return self._data.get("use_task_scheduler", False)

    @use_task_scheduler.setter
    def use_task_scheduler(self, value: bool):
        self._data["use_task_scheduler"] = value
        self.save()
