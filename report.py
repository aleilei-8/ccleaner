# -*- coding: utf-8 -*-
"""清理报告生成模块 v3.0

生成美观的 HTML 清理报告，包含：
- 清理总览（释放空间、删除项、跳过项）
- 各类别详细统计
- 扫描中遇到的权限问题提示
- 操作时间

风格：学术科技蓝 / Ocean Gradient 配色。
"""

import os
import datetime
from typing import Dict, List, Optional

from cleaner import CleanResult

import logging
logger = logging.getLogger(__name__)


def generate_clean_report(
    clean_result: CleanResult,
    scan_results: Optional[Dict] = None,
    permission_errors: Optional[List[str]] = None,
    output_path: Optional[str] = None,
) -> str:
    """生成 HTML 清理报告。

    Args:
        clean_result: CleanResult 清理结果。
        scan_results: 扫描结果字典（可选，用于展示更多细节）。
        permission_errors: 扫描时遇到的权限错误目录列表。
        output_path: 输出文件路径，默认生成到临时目录。

    Returns:
        生成的 HTML 文件路径。
    """
    now = datetime.datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    if output_path is None:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
        os.makedirs(out_dir, exist_ok=True)
        output_path = os.path.join(out_dir, f"clean_report_{now.strftime('%Y%m%d_%H%M%S')}.html")

    mode = "模拟清理（未实际删除）" if clean_result.dry_run else "实际清理"
    total_freed = clean_result.size_freed
    total_deleted = clean_result.files_deleted
    total_skipped = clean_result.files_skipped

    # 类别统计行
    category_rows = ""
    if clean_result.by_category:
        sorted_cats = sorted(
            clean_result.by_category.items(),
            key=lambda x: x[1].get("freed", 0),
            reverse=True,
        )
        for cat_name, stat in sorted_cats:
            deleted = stat.get("deleted", 0)
            freed = stat.get("freed", 0)
            skipped = stat.get("skipped", 0)
            category_rows += f"""
            <tr>
                <td>{_escape(cat_name)}</td>
                <td class="num">{deleted}</td>
                <td class="num">{_format(freed)}</td>
                <td class="num">{skipped}</td>
            </tr>"""
    else:
        category_rows = '<tr><td colspan="4" class="empty">无数据</td></tr>'

    # 权限错误提示
    perm_html = ""
    if permission_errors:
        items = "".join(f"<li>{_escape(p)}</li>" for p in permission_errors[:20])
        more = f"<li>... 共 {len(permission_errors)} 个</li>" if len(permission_errors) > 20 else ""
        perm_html = f"""
        <div class="warn-box">
            <h3>⚠️ 需管理员权限的目录（{len(permission_errors)} 个）</h3>
            <p>以下目录因权限不足未能完全扫描/清理。建议<strong>以管理员身份运行</strong>本程序后重试：</p>
            <ul>{items}{more}</ul>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>C盘清理大师 - 清理报告</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
        background: linear-gradient(135deg, #0a1f3c 0%, #14305c 50%, #1a4d8f 100%);
        color: #e8eef7; padding: 32px; min-height: 100vh;
    }}
    .container {{ max-width: 900px; margin: 0 auto; background: rgba(10,25,50,0.75);
        border-radius: 16px; padding: 36px; backdrop-filter: blur(8px);
        border: 1px solid rgba(90,160,255,0.25); }}
    h1 {{ font-size: 26px; margin-bottom: 6px; background: linear-gradient(90deg,#5aa0ff,#7fd0ff);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
    .subtitle {{ color: #8fb4e0; font-size: 13px; margin-bottom: 24px; }}
    .cards {{ display: flex; gap: 16px; margin-bottom: 28px; flex-wrap: wrap; }}
    .card {{ flex: 1; min-width: 150px; background: linear-gradient(135deg, rgba(40,90,160,0.5), rgba(30,60,120,0.4));
        border-radius: 12px; padding: 18px; text-align: center; border: 1px solid rgba(90,160,255,0.2); }}
    .card .value {{ font-size: 24px; font-weight: 700; color: #9fd8ff; }}
    .card .label {{ font-size: 12px; color: #a8c4e8; margin-top: 6px; }}
    h2 {{ font-size: 17px; margin: 24px 0 12px; color: #9fd8ff; border-left: 3px solid #5aa0ff; padding-left: 10px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid rgba(90,160,255,0.15); }}
    th {{ background: rgba(30,70,130,0.5); color: #bcd6f5; font-weight: 600; }}
    td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .empty {{ text-align: center; color: #7b97bb; }}
    .warn-box {{ background: rgba(255,170,60,0.12); border: 1px solid rgba(255,170,60,0.35);
        border-radius: 10px; padding: 16px; margin-top: 20px; }}
    .warn-box h3 {{ color: #ffc878; font-size: 15px; margin-bottom: 8px; }}
    .warn-box ul {{ margin-left: 20px; font-size: 13px; }}
    .warn-box li {{ margin: 3px 0; color: #e0c89a; word-break: break-all; }}
    .footer {{ margin-top: 28px; text-align: center; color: #6f8db0; font-size: 12px; }}
    .mode-tag {{ display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 12px;
        background: {'rgba(255,170,60,0.2)' if clean_result.dry_run else 'rgba(90,200,140,0.2)'};
        color: {'#ffc878' if clean_result.dry_run else '#8fe0b0'}; }}
</style>
</head>
<body>
<div class="container">
    <h1>C盘清理大师 · 清理报告</h1>
    <div class="subtitle">生成时间：{timestamp} &nbsp;|&nbsp; 模式：<span class="mode-tag">{mode}</span></div>

    <div class="cards">
        <div class="card"><div class="value">{_format(total_freed)}</div><div class="label">释放空间</div></div>
        <div class="card"><div class="value">{total_deleted}</div><div class="label">删除项</div></div>
        <div class="card"><div class="value">{total_skipped}</div><div class="label">跳过项</div></div>
        <div class="card"><div class="value">{len(clean_result.by_category)}</div><div class="label">处理类别</div></div>
    </div>

    <h2>各类别清理统计</h2>
    <table>
        <thead><tr><th>类别</th><th class="num">删除</th><th class="num">释放空间</th><th class="num">跳过</th></tr></thead>
        <tbody>{category_rows}</tbody>
    </table>

    {perm_html}

    <div class="footer">C盘清理大师 v3.0 · 安全清理，绝不误删系统文件</div>
</div>
</body>
</html>"""

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info("清理报告已生成: %s", output_path)
    except IOError as e:
        logger.error("生成报告失败: %s", e)

    return output_path


def _format(size_bytes: int) -> str:
    """格式化字节大小。"""
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
    return f"{size:.1f} {units[idx]}"


def _escape(text: str) -> str:
    """HTML 转义。"""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))
