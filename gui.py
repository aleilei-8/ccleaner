# -*- coding: utf-8 -*-
"""GUI 界面模块 v3.3

v3.3 重构：
- 全新品牌图标：窗口 / 任务栏 / 侧栏 Logo 统一使用生成的精致 App 图标；
- 左侧导航重构为「分组 + 专区切割」：更大的字号、更宽松的间距、当前项高亮，
  并将「分析」拆为两个并列子菜单：📊 C盘分析 与 📦 文件迁移；
- 整体视觉更大气、层次更清晰（品牌区 / 主菜单 / 分析工具 / 底部权限状态）。
"""

import os
import sys
import logging
import threading
import datetime
import tkinter as tk
import tkinter.filedialog as filedialog
import customtkinter as ctk
from typing import Dict, Optional, List

from scanner import Scanner, ScanCategory
from cleaner import Cleaner, CleanResult, AutoCleaner
from quarantine import Quarantine
from config import Config, get_default_categories
from utils import get_disk_usage, format_size, get_disk_usage_percent, is_process_elevated
from analyzer import SpaceAnalyzer, SpaceAnalysis
from systemtools import (
    get_installed_programs, get_startup_items, set_startup_enabled,
    uninstall_program, find_registry_residuals, delete_registry_residual,
    create_task_scheduler, remove_task_scheduler, move_file_to_drive,
)
from report import generate_clean_report

logger = logging.getLogger(__name__)


class CleanerGUI(ctk.CTk):
    """C盘清理大师主界面 v3.3。"""

    COLOR_ACCENT = "#1E88E5"
    COLOR_ACCENT_DK = "#0B3DA0"
    COLOR_SUCCESS = "#43A047"
    COLOR_WARNING = "#FB8C00"
    COLOR_DANGER = "#E53935"
    COLOR_BG_DARK = "#0f1422"
    COLOR_BG_CARD = "#161d33"
    COLOR_BG_FRAME = "#1d2742"
    BORDER = "#2b3566"
    TEXT = "#cdd9f0"
    SUBTEXT = "#8aa0c4"
    MUTED = "#5f7196"

    # 生成的图标文件（build 后会优先使用 app_icon.png / app_icon.ico）
    _GENERATED_ICON = "Modern_flat_app_icon_for_a_Win_2026-11-08T15-26-22.png"

    def __init__(self):
        super().__init__()

        self.title("C盘清理大师 v3.3")
        self.geometry("1100x780")
        self.minsize(900, 660)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.configure(fg_color=self.COLOR_BG_DARK)

        # 核心组件
        self._config = Config()
        self._scanner = Scanner()
        self._cleaner = Cleaner()
        self._quarantine = Quarantine()
        self._auto_cleaner = AutoCleaner(self._cleaner, self._scanner)
        self._scan_results: Dict[str, ScanCategory] = {}
        self._category_vars: Dict[str, ctk.BooleanVar] = {}
        self._scan_thread: Optional[threading.Thread] = None
        self._analyze_thread: Optional[threading.Thread] = None
        self._nav_buttons: Dict[str, ctk.CTkButton] = {}
        self._migrate_rows: Dict[str, tuple] = {}        # 迁移页：path -> (row, btn, label)
        self._analyze_large_rows: Dict[str, tuple] = {}   # 分析页大文件：path -> (row, btn, label)
        self._migrate_selected_path: Optional[str] = None
        self._current_view: str = "概览"
        self._smart_clean_pending: bool = False
        self._current_clean_group: str = "quick"
        self._dry_run_mode: bool = self._config.dry_run_default
        self._brand_img = None
        self._brand_img_lg = None
        self._tk_icon = None

        self._load_icon()
        self._build_layout()
        self._refresh_dashboard()
        self._log("欢迎使用 C盘清理大师 v3.3")

    # ======================== 图标 ========================

    def _resource_path(self, name: str) -> str:
        """解析打包后 / 开发时的资源路径。"""
        if getattr(sys, "frozen", False):
            base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base, name)

    def _find_icon(self) -> Optional[str]:
        for cand in ("app_icon.png", self._GENERATED_ICON, "app_icon.ico"):
            p = self._resource_path(cand)
            if os.path.exists(p):
                return p
        return None

    def _load_icon(self):
        """加载品牌图标：窗口图标（tk.PhotoImage，无需 PIL）+ 侧栏 Logo（CTkImage，需 PIL）。"""
        path = self._find_icon()
        if not path:
            return
        try:
            self._tk_icon = tk.PhotoImage(file=path)
            self.iconphoto(True, self._tk_icon)
        except Exception as e:
            logger.warning("窗口图标加载失败: %s", e)
        try:
            from PIL import Image
            img = Image.open(path).convert("RGBA")
            self._brand_img = ctk.CTkImage(light_image=img, dark_image=img, size=(30, 30))
            self._brand_img_lg = ctk.CTkImage(light_image=img, dark_image=img, size=(54, 54))
        except Exception:
            self._brand_img = None
            self._brand_img_lg = None

    # ======================== 顶层布局 ========================

    def _build_layout(self):
        # 顶部标题栏
        self._header = ctk.CTkFrame(self, fg_color=self.COLOR_BG_CARD, corner_radius=0, height=60)
        self._header.pack(fill="x", side="top")
        self._header.pack_propagate(False)

        if self._brand_img:
            ctk.CTkLabel(self._header, image=self._brand_img, text="").pack(side="left", padx=(16, 6))
        ctk.CTkLabel(
            self._header, text="C盘清理大师",
            font=ctk.CTkFont(size=18, weight="bold"), text_color="#eaf2ff",
        ).pack(side="left")
        ctk.CTkLabel(
            self._header, text="v3.3", font=ctk.CTkFont(size=10),
            text_color="#9fd8ff", fg_color="#16335f", corner_radius=6,
        ).pack(side="left", padx=(8, 0))

        self._disk_label = ctk.CTkLabel(
            self._header, text="C 盘信息加载中...",
            font=ctk.CTkFont(size=12), text_color="#9fd8ff",
        )
        self._disk_label.pack(side="left", padx=24)

        self._perm_label = ctk.CTkLabel(
            self._header, text="", font=ctk.CTkFont(size=11), text_color="#ffc878",
        )
        self._perm_label.pack(side="right", padx=14)

        # 主体：左侧栏 + 内容
        self._body = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self._body.pack(fill="both", expand=True, side="top")

        # 左侧导航栏
        self._sidebar = ctk.CTkFrame(self._body, fg_color=self.COLOR_BG_CARD, width=252, corner_radius=0)
        self._sidebar.pack(side="left", fill="y")
        self._sidebar.pack_propagate(False)

        self._build_sidebar()

        # 内容区
        self._content = ctk.CTkFrame(self._body, fg_color=self.COLOR_BG_DARK, corner_radius=0)
        self._content.pack(side="left", fill="both", expand=True)

        # 管理员权限提示横幅（未提权时显示）
        if not is_process_elevated():
            self._admin_banner = ctk.CTkFrame(self._content, fg_color="#3a2a14", corner_radius=10)
            self._admin_banner.pack(fill="x", padx=18, pady=(16, 0))
            ctk.CTkLabel(
                self._admin_banner,
                text="⚠ 当前未以管理员身份运行：WinSxS / 系统还原点 / 休眠文件等系统级清理需要管理员权限",
                font=ctk.CTkFont(size=11), text_color="#ffcf8f",
            ).pack(side="left", padx=14, pady=10)
            ctk.CTkButton(
                self._admin_banner, text="以管理员重启", width=120, height=30,
                fg_color=self.COLOR_WARNING, command=self._relaunch_admin,
            ).pack(side="right", padx=14, pady=10)

        # 视图容器
        self._view_container = ctk.CTkFrame(self._content, fg_color="transparent", corner_radius=0)
        self._view_container.pack(fill="both", expand=True, padx=18, pady=16)

        # 底部全局状态栏
        self._status_bar = ctk.CTkFrame(self._content, fg_color=self.COLOR_BG_CARD, corner_radius=10, height=34)
        self._status_bar.pack(fill="x", padx=18, pady=(0, 16))
        self._status_bar.pack_propagate(False)
        self._status_label = ctk.CTkLabel(
            self._status_bar, text="就绪", text_color=self.SUBTEXT, font=ctk.CTkFont(size=11))
        self._status_label.pack(side="left", padx=14, pady=4)

        # 构建各视图
        self._views: Dict[str, ctk.CTkFrame] = {}
        self._build_dashboard_view()
        self._build_clean_view()
        self._build_cdisk_view()
        self._build_migrate_view()
        self._build_manage_view()
        self._build_restore_view()
        self._build_settings_view()

        self._show_view("概览")

    def _build_sidebar(self):
        """构建品牌区 + 分组导航（主菜单 / 分析工具）+ 底部权限状态。"""
        # 品牌区
        brand = ctk.CTkFrame(self._sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=20, pady=(22, 6))
        if self._brand_img_lg:
            ctk.CTkLabel(brand, image=self._brand_img_lg, text="").pack(side="left", padx=(0, 12))
        title = ctk.CTkFrame(brand, fg_color="transparent")
        title.pack(side="left", fill="x")
        ctk.CTkLabel(
            title, text="C盘清理大师", font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#eaf2ff",
        ).pack(anchor="w")
        ctk.CTkLabel(
            title, text="智能 · 安全 · 彻底清理", font=ctk.CTkFont(size=11),
            text_color=self.SUBTEXT,
        ).pack(anchor="w", pady=(2, 0))

        # 分隔线
        sep = ctk.CTkFrame(self._sidebar, height=1, fg_color=self.BORDER)
        sep.pack(fill="x", padx=20, pady=(10, 4))

        nav = ctk.CTkFrame(self._sidebar, fg_color="transparent")
        nav.pack(fill="both", expand=True, padx=14)

        # 主菜单
        self._section_label(nav, "主 菜 单")
        for key, icon in [("概览", "🏠"), ("清理", "🧹"), ("管理", "🛠"),
                          ("恢复站", "♻️"), ("设置", "⚙️")]:
            self._make_nav_button(nav, key, icon, sub=False)

        # 分析工具（两个并列子菜单）
        self._section_label(nav, "分 析 工 具")
        sub = ctk.CTkFrame(nav, fg_color="transparent")
        sub.pack(fill="x", padx=8, pady=(2, 6))
        sub.grid_columnconfigure(0, weight=1)
        sub.grid_columnconfigure(1, weight=1)
        self._make_nav_button(sub, "C盘分析", "📊", sub=True, col=0)
        self._make_nav_button(sub, "文件迁移", "📦", sub=True, col=1)

        # 底部权限状态
        foot = ctk.CTkFrame(self._sidebar, fg_color="transparent")
        foot.pack(fill="x", side="bottom", padx=20, pady=(0, 16))
        ctk.CTkFrame(foot, height=1, fg_color=self.BORDER).pack(fill="x", pady=(0, 10))
        self._sidebar_status = ctk.CTkLabel(
            foot, text="", font=ctk.CTkFont(size=11), text_color=self.SUBTEXT,
        )
        self._sidebar_status.pack(anchor="w")
        if is_process_elevated():
            self._sidebar_status.configure(text="● 已以管理员运行", text_color=self.COLOR_SUCCESS)
        else:
            self._sidebar_status.configure(
                text="● 普通权限（系统级清理需管理员）", text_color=self.COLOR_WARNING)

    def _section_label(self, parent, text: str):
        ctk.CTkLabel(
            parent, text=text, font=ctk.CTkFont(size=11, weight="bold"),
            text_color=self.MUTED,
        ).pack(anchor="w", padx=10, pady=(14, 6))

    def _make_nav_button(self, parent, key, icon, sub=False, col=None):
        if sub:
            btn = ctk.CTkButton(
                parent, text=f"{icon} {key}", anchor="center",
                height=42, corner_radius=9, border_width=1, border_color=self.BORDER,
                fg_color="transparent", text_color=self.SUBTEXT, hover_color="#222b47",
                font=ctk.CTkFont(size=13),
                command=lambda k=key: self._show_view(k),
            )
            btn.grid(row=0, column=col, padx=4, pady=4, sticky="ew")
        else:
            btn = ctk.CTkButton(
                parent, text=f"  {icon}   {key}", anchor="w",
                height=48, corner_radius=10, fg_color="transparent",
                text_color=self.SUBTEXT, hover_color="#222b47",
                font=ctk.CTkFont(size=14),
                command=lambda k=key: self._show_view(k),
            )
            btn.pack(fill="x", padx=6, pady=7)
        self._nav_buttons[key] = btn
        return btn

    # ---------- 通用 UI 构件 ----------

    def _card(self, parent, title=None, **kw):
        """创建一个带标题的卡片（功能分区）。"""
        f = ctk.CTkFrame(
            parent, fg_color=self.COLOR_BG_CARD, border_color=self.BORDER,
            border_width=1, corner_radius=12, **kw)
        if title:
            ctk.CTkLabel(
                f, text=title, font=ctk.CTkFont(size=13, weight="bold"), text_color="#9fd8ff",
            ).pack(anchor="w", padx=16, pady=(14, 8))
        return f

    def _stat_card(self, parent, title, value):
        """创建一个统计数字卡片，返回带 _value_label 属性的框架。"""
        f = ctk.CTkFrame(
            parent, fg_color=self.COLOR_BG_CARD, border_color=self.BORDER, border_width=1, corner_radius=12)
        ctk.CTkLabel(f, text=title, font=ctk.CTkFont(size=11), text_color=self.SUBTEXT).pack(
            anchor="w", padx=16, pady=(14, 2))
        val = ctk.CTkLabel(f, text=value, font=ctk.CTkFont(size=18, weight="bold"), text_color="#e6f0ff")
        val.pack(anchor="w", padx=16, pady=(0, 14))
        f._value_label = val
        return f

    def _show_view(self, name: str):
        """切换显示指定视图。"""
        for f in self._views.values():
            if f is not None:
                f.pack_forget()
        view = self._views.get(name)
        if view:
            view.pack(fill="both", expand=True)
        for k, btn in self._nav_buttons.items():
            active = (k == name)
            if k in ("C盘分析", "文件迁移"):
                btn.configure(
                    fg_color=self.COLOR_ACCENT if active else "transparent",
                    text_color="#ffffff" if active else self.SUBTEXT,
                    border_color=self.COLOR_ACCENT if active else self.BORDER,
                    hover_color=self.COLOR_ACCENT if active else "#222b47",
                )
            else:
                btn.configure(
                    fg_color=self.COLOR_ACCENT if active else "transparent",
                    text_color="#ffffff" if active else self.SUBTEXT,
                    hover_color=self.COLOR_ACCENT if active else "#222b47",
                )
        self._current_view = name
        if name == "概览":
            self._refresh_dashboard()
        elif name == "恢复站":
            self._refresh_restore_tab()
        elif name == "清理":
            self._refresh_category_list()

    # ======================== 概览（仪表盘）视图 ========================

    def _build_dashboard_view(self):
        v = ctk.CTkFrame(self._view_container, fg_color="transparent")
        self._views["概览"] = v

        top = ctk.CTkFrame(v, fg_color="transparent")
        top.pack(fill="x", pady=(0, 14))

        donut_card = self._card(top, "C 盘空间", width=320)
        donut_card.pack(side="left", padx=(0, 14), fill="y")
        self._donut = tk.Canvas(
            donut_card, width=180, height=180, bg=self.COLOR_BG_CARD, highlightthickness=0)
        self._donut.pack(padx=16, pady=(8, 4))
        self._donut_text = ctk.CTkLabel(
            donut_card, text="", font=ctk.CTkFont(size=11), text_color=self.SUBTEXT)
        self._donut_text.pack(pady=(0, 12))

        stats = ctk.CTkFrame(top, fg_color="transparent")
        stats.pack(side="left", fill="both", expand=True)
        stats.grid_columnconfigure(0, weight=1)
        stats.grid_columnconfigure(1, weight=1)
        stats.grid_rowconfigure(0, weight=1)
        stats.grid_rowconfigure(1, weight=1)
        self._stat_total = self._stat_card(stats, "总容量", "-")
        self._stat_used = self._stat_card(stats, "已用", "-")
        self._stat_free = self._stat_card(stats, "可用", "-")
        self._stat_recover = self._stat_card(stats, "可清理(估)", "扫描后显示")
        self._stat_total.grid(row=0, column=0, padx=7, pady=7, sticky="nsew")
        self._stat_used.grid(row=0, column=1, padx=7, pady=7, sticky="nsew")
        self._stat_free.grid(row=1, column=0, padx=7, pady=7, sticky="nsew")
        self._stat_recover.grid(row=1, column=1, padx=7, pady=7, sticky="nsew")

        mid = ctk.CTkFrame(v, fg_color="transparent")
        mid.pack(fill="x", pady=(0, 14))

        health = self._card(mid, "系统健康评分")
        health.pack(side="left", padx=(0, 14), fill="both", expand=True)
        self._health_label = ctk.CTkLabel(
            health, text="--", font=ctk.CTkFont(size=32, weight="bold"), text_color="#e6f0ff")
        self._health_label.pack(padx=16, pady=(8, 0))
        self._health_desc = ctk.CTkLabel(
            health, text="扫描后评估", text_color=self.SUBTEXT, font=ctk.CTkFont(size=11))
        self._health_desc.pack(padx=16, pady=(2, 14))

        qa = self._card(mid, "快捷操作")
        qa.pack(side="left", fill="both", expand=True)
        ctk.CTkButton(
            qa, text="🔍 快速扫描", command=self._on_scan,
            fg_color=self.COLOR_ACCENT, width=150, height=36,
        ).pack(anchor="w", padx=16, pady=(10, 6))
        ctk.CTkButton(
            qa, text="🚀 智能清理", command=self._on_smart_clean,
            fg_color=self.COLOR_SUCCESS, width=150, height=36,
        ).pack(anchor="w", padx=16, pady=(0, 6))
        ctk.CTkButton(
            qa, text="📊 空间分析", command=lambda: self._show_view("C盘分析"),
            fg_color=self.COLOR_BG_FRAME, width=150, height=36,
        ).pack(anchor="w", padx=16, pady=(0, 14))

        tip = self._card(v, "使用建议")
        tip.pack(fill="x")
        ctk.CTkLabel(
            tip,
            text="• 普通缓存清理无需管理员；WinSxS / 系统还原点 / 休眠文件等系统级清理请右键「以管理员身份运行」。\n"
                 "• 隔离模式默认开启：清理文件先进入恢复站，可一键还原，绝不永久误删。\n"
                 "• 定期使用「智能清理」可保持 C 盘清爽；大文件可在「文件迁移」中移动到其他盘。",
            font=ctk.CTkFont(size=11), text_color=self.SUBTEXT, justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 14))

    def _refresh_dashboard(self):
        try:
            total, used, free = get_disk_usage("C:\\")
            pct = get_disk_usage_percent("C:\\")
            self._draw_donut(self._donut, pct)
            self._donut_text.configure(text=f"已用 {format_size(used)} / 共 {format_size(total)}")
            self._stat_total._value_label.configure(text=format_size(total))
            self._stat_used._value_label.configure(text=format_size(used))
            self._stat_free._value_label.configure(text=format_size(free))
            if self._scan_results:
                rec = sum(r.total_size for r in self._scan_results.values())
                self._stat_recover._value_label.configure(text=format_size(rec))
            score, desc, color = self._compute_health(pct, free)
            self._health_label.configure(text=str(score), text_color=color)
            self._health_desc.configure(text=desc)
        except Exception as e:
            logger.error("刷新仪表盘失败: %s", e)

    def _compute_health(self, pct, free_bytes):
        if pct >= 95:
            return (28, "磁盘极度紧张，请立即清理", self.COLOR_DANGER)
        if pct >= 85:
            return (55, "空间偏紧，建议尽快清理", self.COLOR_WARNING)
        if pct >= 70:
            return (78, "空间正常，可定期优化", "#9fd8ff")
        return (93, "空间充足，状态良好", self.COLOR_SUCCESS)

    def _draw_donut(self, canvas, percent):
        canvas.delete("all")
        w = canvas.winfo_width() or 180
        h = canvas.winfo_height() or 180
        cx, cy = w // 2, h // 2
        r = min(w, h) // 2 - 16
        canvas.create_oval(cx - r, cy - r, cx + r, cy + r, outline=self.BORDER, width=16)
        extent = 359.999 * max(0.0, min(1.0, percent / 100.0))
        color = self.COLOR_ACCENT
        if percent >= 90:
            color = self.COLOR_DANGER
        elif percent >= 75:
            color = self.COLOR_WARNING
        canvas.create_arc(
            cx - r, cy - r, cx + r, cy + r, start=90, extent=-extent,
            outline=color, width=16, style="arc")
        canvas.create_text(cx, cy - 8, text=f"{percent:.0f}%", fill="#eaf2ff",
                           font=("Segoe UI", 24, "bold"))
        canvas.create_text(cx, cy + 18, text="已使用", fill=self.SUBTEXT, font=("Segoe UI", 10))

    def _on_smart_clean(self):
        self._smart_clean_pending = True
        self._log("智能清理：开始扫描安全类别…")
        self._on_scan()

    # ======================== 清理视图 ========================

    def _build_clean_view(self):
        v = ctk.CTkFrame(self._view_container, fg_color="transparent")
        self._views["清理"] = v

        action = self._card(v, "扫描与清理")
        action.pack(fill="x", pady=(0, 12))
        row = ctk.CTkFrame(action, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 10))
        self._scan_btn = ctk.CTkButton(
            row, text="🔍 扫描垃圾文件", command=self._on_scan,
            fg_color=self.COLOR_ACCENT, width=160, height=36,
        )
        self._scan_btn.pack(side="left", padx=(0, 8))
        self._clean_btn = ctk.CTkButton(
            row, text="🧹 一键清理", command=self._on_clean,
            fg_color=self.COLOR_SUCCESS, width=140, height=36,
        )
        self._clean_btn.pack(side="left", padx=8)
        self._dry_run_var = ctk.BooleanVar(value=self._dry_run_mode)
        self._dry_run_chk = ctk.CTkSwitch(
            row, text="模拟清理（只预览不删除）", variable=self._dry_run_var,
            command=self._on_dry_run_toggle,
        )
        self._dry_run_chk.pack(side="left", padx=16)

        self._scan_progress = ctk.CTkProgressBar(action, height=9)
        self._scan_progress.pack(fill="x", padx=16, pady=(0, 4))
        self._scan_progress.set(0)
        self._scan_status_label = ctk.CTkLabel(
            action, text="", font=ctk.CTkFont(size=11), text_color=self.SUBTEXT)
        self._scan_status_label.pack(anchor="w", padx=16, pady=(0, 12))

        cat = self._card(v, "清理类别（快速 / 深度）")
        cat.pack(fill="both", expand=True, pady=(0, 12))
        seg = ctk.CTkFrame(cat, fg_color="transparent")
        seg.pack(fill="x", padx=16, pady=(0, 6))
        self._clean_segment = ctk.CTkSegmentedButton(
            seg, values=["快速清理", "深度清理"], command=self._on_clean_group_switch)
        self._clean_segment.set("快速清理")
        self._clean_segment.pack(anchor="w")
        self._select_all_var = ctk.BooleanVar(value=True)
        self._select_all_chk = ctk.CTkCheckBox(
            cat, text="全选 / 取消全选", variable=self._select_all_var,
            command=self._on_select_all, font=ctk.CTkFont(size=12, weight="bold"))
        self._select_all_chk.pack(anchor="w", padx=16, pady=(8, 4))
        self._list_frame = ctk.CTkScrollableFrame(cat, fg_color="transparent")
        self._list_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        sumc = self._card(v, "清理摘要 / 日志")
        sumc.pack(fill="x")
        self._summary_label = ctk.CTkLabel(
            sumc, text="扫描后显示可清理内容", font=ctk.CTkFont(size=12), text_color="#a8c4e8")
        self._summary_label.pack(anchor="w", padx=16, pady=(0, 6))
        self._log_box = ctk.CTkTextbox(
            sumc, height=120, fg_color="#0b1120", text_color="#bcd6f5",
            font=ctk.CTkFont(size=11))
        self._log_box.pack(fill="x", padx=16, pady=(0, 14))

    def _on_clean_group_switch(self, value):
        self._current_clean_group = "quick" if value == "快速清理" else "deep"
        self._refresh_category_list()

    def _refresh_category_list(self):
        for widget in list(self._list_frame.winfo_children()):
            if widget is not self._select_all_chk:
                widget.destroy()
        self._category_vars.clear()

        cats = get_default_categories()
        group = getattr(self, "_current_clean_group", "quick")

        any_item = False
        for name, cfg in cats.items():
            if cfg.get("tab", "quick") != group:
                continue
            any_item = True
            enabled_default = cfg.get("default_enabled", True)
            var = ctk.BooleanVar(value=enabled_default)
            self._category_vars[name] = var

            desc = cfg.get("description", "")
            target = cfg.get("clean_target", "files")
            target_str = {"dir": "整目录", "files": "按文件", "shell": "系统API", "command": "系统命令"}.get(target, "")
            if cfg.get("requires_admin"):
                target_str = (target_str + " | ⚠需管理员") if target_str else "⚠需管理员"
            if cfg.get("risk_level") == "high":
                target_str = (target_str + " | 高危") if target_str else "高危"

            row = ctk.CTkFrame(self._list_frame, fg_color="transparent")
            row.pack(fill="x", padx=6, pady=2)

            chk = ctk.CTkCheckBox(
                row, text=f"{name}", variable=var, font=ctk.CTkFont(size=12),
            )
            chk.pack(side="left", padx=8, pady=4)

            info = ctk.CTkLabel(
                row, text=f"{desc}  [{target_str}]",
                font=ctk.CTkFont(size=10), text_color="#7b97bb",
            )
            info.pack(side="left", padx=8, pady=4)

        if not any_item:
            ctk.CTkLabel(
                self._list_frame, text="该分组暂无类别",
                text_color="#7b97bb", font=ctk.CTkFont(size=11),
            ).pack(padx=10, pady=8)

    def _on_select_all(self):
        val = self._select_all_var.get()
        for var in self._category_vars.values():
            var.set(val)

    def _on_dry_run_toggle(self):
        self._dry_run_mode = self._dry_run_var.get()
        self._config.dry_run_default = self._dry_run_mode
        self._log(f"模拟清理模式：{'开启' if self._dry_run_mode else '关闭'}")

    def _on_scan(self):
        if self._scan_thread and self._scan_thread.is_alive():
            self._scanner.cancel()
            self._log("已在请求取消扫描...")
            return

        self._scan_btn.configure(text="⏹ 取消扫描")
        self._scan_progress.set(0)
        self._scan_status_label.configure(text="准备扫描…")
        self._scanner.set_progress_callback(self._on_scan_progress)
        self._scan_thread = threading.Thread(target=self._scan_worker, daemon=True)
        self._scan_thread.start()

    def _scan_worker(self):
        try:
            self._log("开始扫描垃圾文件...")
            results = self._scanner.scan_all()
            self._scan_results = results

            total_files = sum(r.file_count for r in results.values())
            total_size = sum(r.total_size for r in results.values())
            self.after(0, lambda: self._on_scan_done(total_files, total_size))

            perms = self._scanner.get_permission_errors()
            if perms:
                self.after(0, lambda: self._perm_label.configure(
                    text=f"⚠ {len(perms)} 个目录需管理员权限"))
        except Exception as e:
            self._log(f"扫描异常: {e}")
            self.after(0, lambda: self._scan_btn.configure(text="🔍 扫描垃圾文件"))

    def _on_scan_progress(self, current, total, name):
        if total > 0:
            self.after(0, lambda: self._scan_progress.set(current / total))
        self.after(0, lambda: self._scan_status_label.configure(text=f"扫描中：{name}"))

    def _on_scan_done(self, total_files, total_size):
        self._scan_btn.configure(text="🔍 扫描垃圾文件")
        self._scan_progress.set(1)
        self._scan_status_label.configure(text="扫描完成")
        self._refresh_category_list()
        self._summary_label.configure(
            text=f"扫描完成：发现 {total_files} 项垃圾，可释放 {format_size(total_size)}"
        )
        self._log(f"扫描完成：{total_files} 项，{format_size(total_size)}")
        if self._current_view == "概览":
            self._refresh_dashboard()

        if self._smart_clean_pending:
            self._smart_clean_pending = False
            self._select_safe_only()
            self._show_view("清理")
            self._on_clean()

    def _select_safe_only(self):
        cats = get_default_categories()
        for name, var in self._category_vars.items():
            cfg = cats.get(name, {})
            safe = (not cfg.get("requires_admin")) and (cfg.get("risk_level") != "high")
            var.set(safe)

    def _on_clean(self):
        group = getattr(self, "_current_clean_group", "quick")
        selected = {
            name: cat for name, cat in self._scan_results.items()
            if cat.tab == group and self._category_vars.get(name, ctk.BooleanVar()).get()
        }
        if not selected:
            self._log("请先扫描并选择要清理的类别")
            return

        if not self._dry_run_mode:
            total_size = sum(c.total_size for c in selected.values())
            lines = ["即将清理以下类别（删除前请确认）：\n"]
            for name, cat in selected.items():
                lines.append(f"  • {name}：{cat.file_count} 项 / {format_size(cat.total_size)}")
            lines.append(f"\n合计：{len(selected)} 类，约 {format_size(total_size)}")
            if self._config.use_quarantine:
                lines.append("✔ 隔离模式已开启：文件将先移入隔离区（可一键恢复），不会直接永久删除。")
            else:
                lines.append("⚠ 隔离模式已关闭：文件将被永久删除，不可恢复！")
            if not self._confirm("\n".join(lines)):
                self._log("已取消清理")
                return

        self._log(f"开始清理 {len(selected)} 个类别（{'模拟' if self._dry_run_mode else '实际'}）...")
        threading.Thread(target=self._clean_worker, args=(selected,), daemon=True).start()

    def _clean_worker(self, selected):
        try:
            result = self._cleaner.clean_categories(
                selected, dry_run=self._dry_run_mode,
                use_quarantine=self._config.use_quarantine,
            )
            perms = self._scanner.get_permission_errors()
            report_path = generate_clean_report(result, self._scan_results, perms)
            self.after(0, lambda: self._on_clean_done(result, report_path))
        except Exception as e:
            self._log(f"清理异常: {e}")

    def _on_clean_done(self, result: CleanResult, report_path: str):
        msg = result.summary().replace("\n", " | ")
        self._summary_label.configure(text=msg)
        self._log(msg)
        self._log(f"HTML 报告已生成：{report_path}")
        if result.files_quarantined:
            self._log(f"⚠ {result.files_quarantined} 项已移入隔离区，可在「恢复站」一键恢复")
            try:
                self._refresh_restore_tab()
                self._show_view("恢复站")
            except Exception:
                pass
        self._refresh_disk_info()
        if self._current_view == "概览":
            self._refresh_dashboard()

    # ======================== C盘分析视图 ========================

    def _build_cdisk_view(self):
        v = ctk.CTkFrame(self._view_container, fg_color="transparent")
        self._views["C盘分析"] = v

        ctrl = self._card(v, "空间分析")
        ctrl.pack(fill="x", pady=(0, 12))
        btn_row = ctk.CTkFrame(ctrl, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkButton(
            btn_row, text="📊 开始空间分析", command=self._on_analyze,
            fg_color=self.COLOR_ACCENT, width=160, height=36,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(
            btn_row, text="分析 C 盘目录占用 / 大文件 / 重复文件 / 空文件夹",
            font=ctk.CTkFont(size=11), text_color=self.SUBTEXT,
        ).pack(side="left", padx=12)

        self._analyze_progress = ctk.CTkProgressBar(ctrl, height=9)
        self._analyze_progress.pack(fill="x", padx=16, pady=(0, 12))
        self._analyze_progress.set(0)

        res = self._card(v, "分析结果")
        res.pack(fill="both", expand=True)
        self._analyze_frame = ctk.CTkScrollableFrame(res, fg_color="transparent")
        self._analyze_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        ctk.CTkLabel(
            self._analyze_frame,
            text="点击「开始空间分析」查看 C 盘空间占用、大文件、重复文件",
            text_color="#7b97bb", font=ctk.CTkFont(size=11),
        ).pack(padx=10, pady=20)

    def _on_analyze(self):
        if self._analyze_thread and self._analyze_thread.is_alive():
            self._log("空间分析正在进行中...")
            return
        self._analyze_progress.set(0)
        for w in list(self._analyze_frame.winfo_children()):
            w.destroy()
        self._analyze_thread = threading.Thread(target=self._analyze_worker, daemon=True)
        self._analyze_thread.start()

    def _analyze_worker(self):
        try:
            self._log("开始空间分析（可能需要几分钟）...")
            analyzer = SpaceAnalyzer("C:\\")
            analyzer.set_progress_callback(self._on_analyze_progress)
            analysis = analyzer.run_full_analysis(large_file_threshold_mb=1024)
            self.after(0, lambda: self._show_analysis(analysis))
        except Exception as e:
            self._log(f"空间分析异常: {e}")

    def _on_analyze_progress(self, stage, percent, detail):
        self.after(0, lambda: self._analyze_progress.set(min(percent, 100) / 100.0))

    def _show_analysis(self, analysis: SpaceAnalysis):
        frame = self._analyze_frame
        for w in list(frame.winfo_children()):
            w.destroy()
        self._analyze_large_rows.clear()

        ctk.CTkLabel(
            frame, text=f"📦 大文件（>1GB，共 {len(analysis.large_files)} 个）",
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#9fd8ff").pack(anchor="w", padx=10, pady=(8, 4))
        for lf in analysis.large_files[:30]:
            row = ctk.CTkFrame(frame, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=1)
            label = ctk.CTkLabel(
                row, text=f"{lf.size_str}  {lf.path}",
                font=ctk.CTkFont(size=10), text_color="#bcd6f5")
            label.pack(side="left", padx=4)
            system_file = self._is_system_or_protected(lf.path)
            btn = ctk.CTkButton(
                row, text="迁移" if not system_file else "系统文件",
                width=60, height=26,
                state="normal" if not system_file else "disabled",
                fg_color=self.COLOR_ACCENT if not system_file else "#444",
                command=lambda p=lf.path: self._migrate_file(p),
            )
            btn.pack(side="right", padx=4)
            self._analyze_large_rows[lf.path] = (row, btn, label)

        ctk.CTkLabel(
            frame, text=f"👯 重复文件（{len(analysis.duplicate_groups)} 组，可节省 {format_size(analysis.wasted_total)}）",
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#9fd8ff").pack(anchor="w", padx=10, pady=(10, 4))
        for grp in analysis.duplicate_groups[:15]:
            txt = f"{grp.file_size_str} ×{len(grp.files)} → {grp.files[0]}"
            ctk.CTkLabel(frame, text=txt, font=ctk.CTkFont(size=10),
                         text_color="#bcd6f5", wraplength=760).pack(anchor="w", padx=14, pady=1)

        ctk.CTkLabel(
            frame, text=f"📁 空文件夹（{len(analysis.empty_dirs)} 个已尝试清理）",
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#9fd8ff").pack(anchor="w", padx=10, pady=(10, 4))
        if not analysis.empty_dirs:
            ctk.CTkLabel(frame, text="未发现空文件夹", text_color="#7b97bb",
                         font=ctk.CTkFont(size=10)).pack(anchor="w", padx=14)

        self._log("空间分析完成")
        self._analyze_progress.set(1)

    # ======================== 文件迁移视图 ========================

    def _build_migrate_view(self):
        v = ctk.CTkFrame(self._view_container, fg_color="transparent")
        self._views["文件迁移"] = v

        ctrl = self._card(v, "迁移设置")
        ctrl.pack(fill="x", pady=(0, 12))
        row1 = ctk.CTkFrame(ctrl, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=(0, 8))
        self._migrate_drive_var = ctk.StringVar(value="D:\\")
        ctk.CTkLabel(row1, text="目标盘符：", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 4))
        ctk.CTkEntry(row1, textvariable=self._migrate_drive_var, width=90, height=32).pack(side="left", padx=4)
        ctk.CTkButton(
            row1, text="📂 选择文件", command=self._choose_migrate_file,
            fg_color=self.COLOR_BG_FRAME, width=120, height=32,
        ).pack(side="left", padx=12)
        self._migrate_selected_label = ctk.CTkLabel(
            row1, text="未选择文件", font=ctk.CTkFont(size=11), text_color=self.SUBTEXT)
        self._migrate_selected_label.pack(side="left", padx=8)

        row2 = ctk.CTkFrame(ctrl, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkButton(
            row2, text="🚀 开始迁移", command=self._migrate_selected,
            fg_color=self.COLOR_ACCENT, width=140, height=34,
        ).pack(side="left", padx=(0, 8))
        self._migrate_status = ctk.CTkLabel(
            row2, text="", font=ctk.CTkFont(size=11), text_color="#9be7a0")
        self._migrate_status.pack(side="left", padx=8)

        listc = self._card(v, "迁移记录")
        listc.pack(fill="both", expand=True)
        self._migrate_list_frame = ctk.CTkScrollableFrame(listc, fg_color="transparent")
        self._migrate_list_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        ctk.CTkLabel(
            self._migrate_list_frame,
            text="选择大文件后点击「开始迁移」，文件将移动到目标盘（迁移非删除，可安全释放 C 盘空间）",
            text_color="#7b97bb", font=ctk.CTkFont(size=11),
        ).pack(padx=10, pady=20)

    def _choose_migrate_file(self):
        path = filedialog.askopenfilename(title="选择要迁移的文件")
        if not path:
            return
        self._migrate_selected_path = path
        self._migrate_selected_label.configure(
            text=os.path.basename(path), text_color="#e6f0ff")
        self._log(f"已选择迁移文件：{path}")

    def _migrate_selected(self):
        if not self._migrate_selected_path:
            self._set_migrate_status("请先点击「选择文件」选取要迁移的文件", error=True)
            return
        self._migrate_file(self._migrate_selected_path)

    def _migrate_file(self, path: str):
        dest = self._migrate_drive_var.get().strip()
        if not dest:
            self._set_migrate_status("请先填写目标盘符（如 D:\\）", error=True)
            return
        if self._is_system_or_protected(path):
            self._set_migrate_status(
                f"⚠ 该文件受系统保护，禁止迁移：{os.path.basename(path)}", error=True)
            return
        self._set_migrate_status(
            f"迁移中：{os.path.basename(path)} → {dest} …", error=False)
        threading.Thread(target=lambda: self._do_migrate(path, dest), daemon=True).start()

    def _do_migrate(self, path, dest):
        try:
            ok, new_path, msg = move_file_to_drive(path, dest)
        except Exception as e:
            ok, new_path, msg = False, None, f"迁移异常：{e}"

        if ok:
            self.after(0, lambda: self._set_migrate_status(
                f"✓ {msg}：{os.path.basename(path)} → {new_path}", error=False))
            self._log(f"迁移成功：{path} → {new_path}")
            self.after(0, lambda: self._add_migrate_row(path, new_path))
            self.after(300, lambda: self._mark_migrated(path, new_path))
        else:
            self.after(0, lambda: self._set_migrate_status(
                f"迁移失败：{msg}", error=True))
            self._log(f"迁移失败：{path}（{msg}）")

    def _set_migrate_status(self, text: str, error: bool = False):
        try:
            color = "#ff9a9a" if error else "#9be7a0"
            self._migrate_status.configure(text=text, text_color=color)
        except Exception:
            pass

    def _add_migrate_row(self, path: str, new_path: str):
        """在迁移记录列表中追加一行（避免重复）。"""
        if path in self._migrate_rows:
            return
        row = ctk.CTkFrame(self._migrate_list_frame, fg_color=self.COLOR_BG_FRAME, corner_radius=8)
        row.pack(fill="x", padx=8, pady=3)
        label = ctk.CTkLabel(
            row, text=f"✓ 已迁移 → {new_path}", font=ctk.CTkFont(size=10),
            text_color="#9be7a0", wraplength=720, justify="left")
        label.pack(side="left", padx=10, pady=6)
        btn = ctk.CTkButton(row, text="已迁移", width=70, height=26,
                            state="disabled", fg_color="#2e7d32")
        btn.pack(side="right", padx=8, pady=6)
        self._migrate_rows[path] = (row, btn, label)

    def _mark_migrated(self, path: str, new_path: str):
        """迁移成功后同步更新 C盘分析 页对应大文件行（若存在）。"""
        ref = self._analyze_large_rows.get(path)
        if not ref:
            return
        row, btn, label = ref
        try:
            label.configure(text=f"✓ 已迁移 → {new_path}", text_color="#9be7a0")
            btn.configure(state="disabled", text="已迁移", fg_color="#2e7d32")
        except Exception:
            pass

    def _is_system_or_protected(self, path: str) -> bool:
        norm = os.path.normpath(path).lower()
        prefixes = (r"c:\windows", r"c:\program files", r"c:\program files (x86)",
                    r"c:\programdata", r"c:\system volume information", r"c:\$recycle.bin")
        if any(norm.startswith(p) for p in prefixes):
            return True
        base = os.path.basename(norm)
        if base in ("pagefile.sys", "hiberfil.sys", "swapfile.sys", "dumpstack.log"):
            return True
        return False

    def _relaunch_admin(self):
        try:
            import ctypes
            exe = sys.executable
            ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, "", None, 1)
            if ret > 32:
                self._log("已请求管理员权限，正在重启…")
                self.destroy()
                sys.exit(0)
            else:
                self._log("管理员提权重被取消")
        except Exception as e:
            self._log(f"提权失败: {e}")

    # ======================== 管理视图 ========================

    def _build_manage_view(self):
        v = ctk.CTkFrame(self._view_container, fg_color="transparent")
        self._views["管理"] = v

        ctrl = self._card(v, "系统管理功能")
        ctrl.pack(fill="x", pady=(0, 12))
        btn_row = ctk.CTkFrame(ctrl, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=12)
        ctk.CTkButton(btn_row, text="🔄 启动项", command=self._on_load_startup,
                      fg_color=self.COLOR_ACCENT, width=130, height=34).pack(side="left", padx=6)
        ctk.CTkButton(btn_row, text="📦 已装程序", command=self._on_load_programs,
                      fg_color=self.COLOR_ACCENT, width=130, height=34).pack(side="left", padx=6)
        ctk.CTkButton(btn_row, text="🔧 注册表残留", command=self._on_load_registry,
                      fg_color=self.COLOR_WARNING, width=140, height=34).pack(side="left", padx=6)

        listc = self._card(v, "列表")
        listc.pack(fill="both", expand=True)
        self._manage_frame = ctk.CTkScrollableFrame(listc, fg_color="transparent")
        self._manage_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        ctk.CTkLabel(self._manage_frame, text="选择上方功能加载列表",
                     text_color="#7b97bb", font=ctk.CTkFont(size=11)).pack(padx=10, pady=20)

    def _on_load_startup(self):
        self._clear_manage()
        items = get_startup_items()
        ctk.CTkLabel(self._manage_frame, text=f"启动项（{len(items)} 个）— 禁用可加快开机（可恢复）",
                     font=ctk.CTkFont(size=13, weight="bold"), text_color="#9fd8ff").pack(anchor="w", padx=10, pady=6)
        for item in items:
            row = ctk.CTkFrame(self._manage_frame, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=1)
            ctk.CTkLabel(row, text=f"{item.name}\n{item.command}",
                         font=ctk.CTkFont(size=10), text_color="#bcd6f5", wraplength=620).pack(side="left", padx=6)
            ctk.CTkButton(row, text="禁用" if item.enabled else "启用", width=64, height=28,
                          command=lambda it=item: self._toggle_startup(it)).pack(side="right", padx=4)

    def _toggle_startup(self, item):
        new_state = not item.enabled
        if set_startup_enabled(item, new_state):
            item.enabled = new_state
            self._log(f"启动项 {item.name} 已{'禁用' if not new_state else '启用'}")
            self._on_load_startup()
        else:
            self._log(f"操作失败：{item.name}（可能需要管理员权限）")

    def _on_load_programs(self):
        self._clear_manage()
        programs = get_installed_programs()
        ctk.CTkLabel(self._manage_frame, text=f"已安装程序（{len(programs)} 个）— 点击卸载将调用官方卸载程序",
                     font=ctk.CTkFont(size=13, weight="bold"), text_color="#9fd8ff").pack(anchor="w", padx=10, pady=6)
        for prog in programs:
            row = ctk.CTkFrame(self._manage_frame, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=1)
            label = f"{prog.name}"
            if prog.publisher:
                label += f"  ·  {prog.publisher}"
            if prog.estimated_size_mb:
                label += f"  ·  {prog.estimated_size_mb} MB"
            ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=10),
                         text_color="#bcd6f5", wraplength=620).pack(side="left", padx=6)
            ctk.CTkButton(row, text="卸载", width=64, height=28,
                          fg_color=self.COLOR_DANGER,
                          command=lambda p=prog: self._uninstall(p)).pack(side="right", padx=4)

    def _uninstall(self, prog):
        if not self._confirm(f"确认卸载「{prog.name}」？\n将调用该程序自带的官方卸载程序。"):
            return
        if uninstall_program(prog):
            self._log(f"已启动卸载：{prog.name}")
        else:
            self._log(f"卸载启动失败：{prog.name}")

    def _on_load_registry(self):
        self._clear_manage()
        residuals = find_registry_residuals()
        ctk.CTkLabel(self._manage_frame, text=f"注册表残留（{len(residuals)} 个）— 指向不存在的卸载程序，删除需确认",
                     font=ctk.CTkFont(size=13, weight="bold"), text_color="#9fd8ff").pack(anchor="w", padx=10, pady=6)
        if not residuals:
            ctk.CTkLabel(self._manage_frame, text="未发现注册表残留", text_color="#7b97bb",
                         font=ctk.CTkFont(size=11)).pack(anchor="w", padx=14, pady=6)
        for res in residuals:
            row = ctk.CTkFrame(self._manage_frame, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=1)
            ctk.CTkLabel(row, text=f"{res.key_path}\n{res.value_data}",
                         font=ctk.CTkFont(size=10), text_color="#bcd6f5", wraplength=620).pack(side="left", padx=6)
            ctk.CTkButton(row, text="删除", width=64, height=28, fg_color=self.COLOR_DANGER,
                          command=lambda r=res: self._del_registry(r)).pack(side="right", padx=4)

    def _del_registry(self, res):
        if not self._confirm(f"确认删除注册表项？\n{res.key_path}\n\n此操作不可撤销！"):
            return
        if delete_registry_residual(res):
            self._log(f"已删除注册表残留：{res.key_path}")
            self._on_load_registry()
        else:
            self._log("删除失败（可能需要管理员权限）")

    def _clear_manage(self):
        for w in list(self._manage_frame.winfo_children()):
            w.destroy()

    # ======================== 恢复站视图 ========================

    def _build_restore_view(self):
        v = ctk.CTkFrame(self._view_container, fg_color="transparent")
        self._views["恢复站"] = v

        ctrl = self._card(v, "恢复站操作")
        ctrl.pack(fill="x", pady=(0, 12))
        ctrl_row = ctk.CTkFrame(ctrl, fg_color="transparent")
        ctrl_row.pack(fill="x", padx=16, pady=12)
        ctk.CTkButton(ctrl_row, text="🔄 刷新列表", command=self._refresh_restore_tab,
                      fg_color=self.COLOR_ACCENT, width=130, height=34).pack(side="left", padx=(0, 8))
        ctk.CTkButton(ctrl_row, text="🗑 清空隔离区", command=self._purge_all,
                      fg_color=self.COLOR_DANGER, width=130, height=34).pack(side="left", padx=8)
        self._restore_count_label = ctk.CTkLabel(
            ctrl_row, text="", font=ctk.CTkFont(size=11), text_color="#a8c4e8")
        self._restore_count_label.pack(side="left", padx=10)

        infoc = self._card(v, "说明")
        infoc.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(
            infoc,
            text="隔离模式开启后，清理的文件会先移到这里而不是直接删除。\n"
                 "恢复 = 还原到原路径；永久清除 = 真正删除（不可撤销）。",
            text_color="#7b97bb", font=ctk.CTkFont(size=11), justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 14))

        listc = self._card(v, "隔离项列表")
        listc.pack(fill="both", expand=True)
        self._restore_frame = ctk.CTkScrollableFrame(listc, fg_color="transparent")
        self._restore_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def _refresh_restore_tab(self):
        for w in list(self._restore_frame.winfo_children()):
            w.destroy()
        items = self._quarantine.list_items()
        self._restore_count_label.configure(text=f"共 {len(items)} 项待恢复")
        if not items:
            ctk.CTkLabel(self._restore_frame, text="隔离区为空（清理文件会先进入这里，可一键恢复）",
                         text_color="#7b97bb", font=ctk.CTkFont(size=12)).pack(padx=10, pady=20)
            return
        for it in items:
            row = ctk.CTkFrame(self._restore_frame, fg_color=self.COLOR_BG_FRAME, corner_radius=8)
            row.pack(fill="x", padx=8, pady=3)
            info = (f"{it.get('category', '')} · {os.path.basename(it.get('original_path', ''))}\n"
                    f"原路径: {it.get('original_path', '')}  |  {format_size(it.get('size', 0))}  |  {it.get('time', '')}")
            ctk.CTkLabel(row, text=info, font=ctk.CTkFont(size=10),
                         text_color="#bcd6f5", wraplength=620, justify="left").pack(side="left", padx=8, pady=4)
            ctk.CTkButton(row, text="恢复", width=64, height=28, fg_color=self.COLOR_SUCCESS,
                          command=lambda q=it["id"]: self._restore_item(q)).pack(side="right", padx=4)
            ctk.CTkButton(row, text="永久清除", width=80, height=28, fg_color=self.COLOR_DANGER,
                          command=lambda q=it["id"]: self._purge_item(q)).pack(side="right", padx=4)

    def _restore_item(self, qid: str):
        if self._quarantine.restore(qid):
            self._log(f"已恢复隔离项 {qid}")
        else:
            self._log(f"恢复失败 {qid}（原文件可能已不存在或不可写）")
        self._refresh_restore_tab()

    def _purge_item(self, qid: str):
        if not self._confirm("确认永久清除该项？\n此操作不可撤销！"):
            return
        self._quarantine.purge(qid)
        self._log(f"已永久清除隔离项 {qid}")
        self._refresh_restore_tab()

    def _purge_all(self):
        n = self._quarantine.count()
        if n == 0:
            self._log("隔离区已为空")
            return
        if not self._confirm(f"确认永久清空隔离区（{n} 项）？\n此操作不可撤销！"):
            return
        removed = self._quarantine.purge_all()
        self._log(f"已永久清空隔离区：{removed} 项")
        self._refresh_restore_tab()

    # ======================== 设置视图 ========================

    def _build_settings_view(self):
        v = ctk.CTkScrollableFrame(self._view_container, fg_color="transparent")
        self._views["设置"] = v

        auto = self._card(v, "⚙️ 自动清理设置")
        auto.pack(fill="x", pady=(0, 14))
        self._auto_var = ctk.BooleanVar(value=self._config.auto_clean)
        ctk.CTkSwitch(auto, text="启用自动清理", variable=self._auto_var,
                      command=self._on_auto_toggle).pack(anchor="w", padx=16, pady=8)
        ctk.CTkLabel(auto, text="清理间隔：", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=16, pady=(6, 0))
        self._interval_var = ctk.StringVar(value="每天")
        ctk.CTkSegmentedButton(
            auto, values=list(AutoCleaner.INTERVAL_PRESETS.keys()),
            variable=self._interval_var, command=self._on_interval_change,
        ).pack(anchor="w", padx=16, pady=6)
        self._task_var = ctk.BooleanVar(value=self._config.use_task_scheduler)
        ctk.CTkSwitch(auto, text="使用 Windows 任务计划（后台静默，无需常驻）",
                      variable=self._task_var, command=self._on_task_toggle).pack(anchor="w", padx=16, pady=(6, 12))

        sec = self._card(v, "🛡️ 安全设置")
        sec.pack(fill="x", pady=(0, 14))
        self._protect_large_var = ctk.BooleanVar(value=self._config.protect_large_files)
        ctk.CTkSwitch(sec, text="保护大文件（>4GB 不清理，防误删虚拟机/ISO）",
                      variable=self._protect_large_var, command=self._on_protect_large_toggle).pack(anchor="w", padx=16, pady=8)
        ctk.CTkLabel(sec, text="大文件阈值（MB，用于空间分析）：", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=16, pady=(6, 0))
        self._threshold_entry = ctk.CTkEntry(sec, width=120, height=32)
        self._threshold_entry.insert(0, str(self._config.large_file_threshold_mb))
        self._threshold_entry.pack(anchor="w", padx=16, pady=4)
        ctk.CTkButton(sec, text="保存阈值", width=110, height=30,
                      command=self._on_save_threshold).pack(anchor="w", padx=16, pady=6)
        self._quarantine_var = ctk.BooleanVar(value=self._config.use_quarantine)
        ctk.CTkSwitch(sec, text="隔离模式（删除前移入隔离区，可一键恢复）",
                      variable=self._quarantine_var, command=self._on_quarantine_toggle).pack(anchor="w", padx=16, pady=(6, 12))

        about = self._card(v, "ℹ️ 关于")
        about.pack(fill="x")
        ctk.CTkLabel(
            about,
            text="C盘清理大师 v3.3\n安全清理，三层保护绝不误删系统文件\n"
                 "扫描机制：深度递归 + 环境变量展开 + 权限提示\n"
                 "界面：左侧分组导航 + 卡片分区 + 概览仪表盘",
            font=ctk.CTkFont(size=11), text_color="#a8c4e8", justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 14))

    def _on_auto_toggle(self):
        val = self._auto_var.get()
        self._config.auto_clean = val
        if val:
            self._auto_cleaner.set_dry_run(self._dry_run_mode)
            self._auto_cleaner.start()
            self._log("自动清理已启动")
        else:
            self._auto_cleaner.stop()
            self._log("自动清理已停止")

    def _on_interval_change(self, value):
        hours = AutoCleaner.INTERVAL_PRESETS.get(value, 24)
        self._auto_cleaner.set_interval_hours(hours)
        self._config.auto_clean_interval_hours = hours
        self._log(f"清理间隔设置为：{value}")

    def _on_task_toggle(self):
        use = self._task_var.get()
        self._config.use_task_scheduler = use
        if use:
            exe = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath("main.py")
            if create_task_scheduler("CCleanerAutoClean", exe, self._config.auto_clean_interval_hours):
                self._log("已创建 Windows 任务计划")
            else:
                self._log("任务计划创建失败（需管理员权限）")
                self._task_var.set(False)
        else:
            remove_task_scheduler("CCleanerAutoClean")
            self._log("已移除 Windows 任务计划")

    def _on_protect_large_toggle(self):
        self._config.protect_large_files = self._protect_large_var.get()
        self._log(f"大文件保护：{'开启' if self._protect_large_var.get() else '关闭'}")

    def _on_save_threshold(self):
        try:
            val = int(self._threshold_entry.get())
            self._config.large_file_threshold_mb = max(100, val)
            self._log(f"大文件阈值已保存：{self._config.large_file_threshold_mb} MB")
        except ValueError:
            self._log("阈值输入无效，请输入数字")

    def _on_quarantine_toggle(self):
        val = self._quarantine_var.get()
        self._config.use_quarantine = val
        if val:
            self._log("隔离模式：开启（清理移入隔离区，可一键恢复）")
        else:
            self._log("隔离模式：关闭（清理将永久删除，不可恢复）")

    # ======================== 通用辅助 ========================

    def _refresh_disk_info(self):
        try:
            total, used, free = get_disk_usage("C:\\")
            percent = get_disk_usage_percent("C:\\")
            self._disk_label.configure(
                text=f"C 盘：总 {format_size(total)} | 已用 {format_size(used)} "
                      f"({percent:.1f}%) | 可用 {format_size(free)}"
            )
        except Exception as e:
            self._disk_label.configure(text=f"C 盘信息获取失败: {e}")

    def _log(self, message: str):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        try:
            self._log_box.insert("end", line)
            self._log_box.see("end")
        except Exception:
            pass
        try:
            self._status_label.configure(text=message)
        except Exception:
            pass
        logger.info(message)

    def _confirm(self, message: str) -> bool:
        import tkinter.messagebox as mb
        return mb.askyesno("确认操作", message)
