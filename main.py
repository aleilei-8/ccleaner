# -*- coding: utf-8 -*-
"""C盘清理大师 - 入口文件 v2.1

启动 CustomTkinter GUI 应用程序。
v2.1 修复：PyInstaller --windowed 模式下的静默崩溃问题。
支持 with-console / with-windowed 两种模式。
"""

import os
import sys
import logging
import traceback

# ======================== PyInstaller 路径处理 ========================

def get_app_dir() -> str:
    """获取应用程序目录（兼容 PyInstaller --onefile 打包）。

    PyInstaller --onefile 运行时:
    - sys.executable = EXE 所在目录
    - sys._MEIPASS = 临时解压目录（只读）
    - __file__ = _MEIPASS 下的脚本路径

    对于日志/配置文件等需要写入的文件，使用 EXE 所在目录；
    对于只读资源文件，使用 _MEIPASS。
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后运行
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


def get_resource_dir() -> str:
    """获取资源目录（只读）。"""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    else:
        return os.path.dirname(os.path.abspath(__file__))


PROJECT_DIR = get_app_dir()

# 确保项目根目录在 sys.path 中
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)


def show_error(title: str, message: str):
    """显示错误信息 — 优先使用 GUI 对话框，回退到控制台。

    在 PyInstaller --windowed 模式下没有控制台，
    所以需要用 ctypes MessageBox 或 tkinter messagebox 显示错误。
    """
    error_detail = f"{message}\n\n详细错误:\n{traceback.format_exc()}" if sys.exc_info()[0] else message

    # 尝试写入错误日志到桌面（用户一定能看到）
    try:
        desktop = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
        error_log = os.path.join(desktop, "ccleaner_error.log")
        with open(error_log, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"{error_detail}\n")
    except Exception:
        pass

    # 方法1: 尝试用 ctypes MessageBox（不依赖 tkinter）
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, error_detail, title, 0x10)  # MB_ICONERROR = 0x10
        return
    except Exception:
        pass

    # 方法2: 回退到 tkinter messagebox
    try:
        from tkinter import messagebox
        messagebox.showerror(title, error_detail)
        return
    except Exception:
        pass

    # 方法3: 打印到 stderr（如果有控制台的话）
    print(f"[{title}] {error_detail}", file=sys.stderr)


def main():
    """主入口函数。"""
    # 早期错误日志（在正式 logging 配置之前）
    try:
        log_file = os.path.join(PROJECT_DIR, "cleaner.log")
        from utils import setup_logging
        setup_logging(log_file)

        logger = logging.getLogger(__name__)
        logger.info("=" * 50)
        logger.info("C盘清理大师 v2.1 启动")
        logger.info("EXE 目录: %s", os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else PROJECT_DIR)
        logger.info("应用目录: %s", PROJECT_DIR)
        logger.info("=" * 50)
    except Exception as e:
        show_error("日志初始化失败", f"无法创建日志文件:\n{str(e)}")
        sys.exit(1)

    # 启动 GUI
    try:
        from gui import CleanerGUI
        app = CleanerGUI()
        app.mainloop()
    except Exception as e:
        logger.critical("程序启动失败: %s", e, exc_info=True)
        show_error("C盘清理大师 - 启动失败",
                   f"程序启动时发生错误:\n{str(e)}\n\n"
                   f"详细信息已写入:\n{log_file}")
        sys.exit(1)


if __name__ == "__main__":
    main()
