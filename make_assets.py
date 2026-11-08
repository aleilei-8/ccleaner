# -*- coding: utf-8 -*-
"""生成应用图标资源：app_icon.png（侧栏/窗口）与 app_icon.ico（EXE 文件图标）。

依赖 Pillow。运行：python make_assets.py

说明：ICO 必须包含 16/24/32/48/64/128/256 多尺寸，且小尺寸为标准 BMP，
否则 Windows 资源管理器在文件列表（使用 32px）里会回退到默认程序图标。
Pillow 对单一源图使用 sizes=[...] 即可生成多尺寸 ICO（不要加 append_images/save_all，
那会破坏多帧写入）。
"""
import os
import struct
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "Modern_flat_app_icon_for_a_Win_2026-11-08T15-26-22.png")
PNG_OUT = os.path.join(HERE, "app_icon.png")
ICO_OUT = os.path.join(HERE, "app_icon.ico")

SIZES = [(16, 16), (24, 24), (32, 32), (48, 48),
         (64, 64), (128, 128), (256, 256)]


def ico_frame_count(path: str) -> int:
    """读取 ICO 文件头，返回图像数量（不依赖 Pillow 读取器）。"""
    with open(path, "rb") as f:
        head = f.read(6)
    if head[:4] != b"\x00\x00\x01\x00":
        raise ValueError("不是有效的 ICO 文件")
    return struct.unpack("<H", head[4:6])[0]


def main():
    if not os.path.exists(SRC):
        raise SystemExit(f"未找到源图标: {SRC}")
    img = Image.open(SRC).convert("RGBA")
    # 统一缩放到 512x512 正方形作为母版
    img = img.resize((512, 512), Image.LANCZOS)

    img.save(PNG_OUT)
    # 多尺寸 ICO：单一母版 + sizes 列表（Pillow 会自动缩放并写入多帧）
    img.save(ICO_OUT, sizes=SIZES)

    n = ico_frame_count(ICO_OUT)
    print("已生成:", PNG_OUT)
    print("已生成:", ICO_OUT, f"（包含 {n} 个尺寸帧）")
    if n != len(SIZES):
        raise SystemExit(f"警告：ICO 帧数异常，期望 {len(SIZES)} 实际 {n}")


if __name__ == "__main__":
    main()
