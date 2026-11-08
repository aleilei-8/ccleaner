# -*- coding: utf-8 -*-
"""一键打包 CCleaner.exe（含新图标与图标资源）。

运行：python build_exe.py
依赖：pyinstaller、customtkinter、pillow、psutil 已安装。
"""
import os
import PyInstaller.__main__

HERE = os.path.dirname(os.path.abspath(__file__))
ICON = os.path.join(HERE, "app_icon.ico")
PNG = os.path.join(HERE, "app_icon.png")
sep = os.pathsep  # Windows 上为 ';'

add_data = []
if os.path.exists(PNG):
    add_data += ["--add-data", f"{PNG}{sep}."]
if os.path.exists(ICON):
    add_data += ["--icon", ICON]
else:
    # 退而求其次：直接用源图作图标
    src = os.path.join(HERE, "Modern_flat_app_icon_for_a_Win_2026-11-08T15-26-22.png")
    if os.path.exists(src):
        add_data += ["--icon", src]

PyInstaller.__main__.run([
    "main.py",
    "--name", "CCleaner",
    "--onefile",
    "--windowed",
    "--collect-all", "customtkinter",
    "--hidden-import", "customtkinter",
    "--hidden-import", "darkdetect",
    "--hidden-import", "packaging",
    "--hidden-import", "winreg",
    "--hidden-import", "psutil",
    "--hidden-import", "PIL",
    "--hidden-import", "PIL.Image",
    "--distpath", "dist",
    "--workpath", "build",
    "--clean",
] + add_data)

print("构建完成：dist/CCleaner.exe")
