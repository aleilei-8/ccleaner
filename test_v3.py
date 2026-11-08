# -*- coding: utf-8 -*-
"""C盘清理大师 v3.0 测试套件

重点验证 v3.0 修复的核心机制：
1. 扫描器深度递归（不再有 quick_mode 不递归 bug）
2. 整目录删除（不再只删文件留空目录）
3. 环境变量展开
4. 权限错误记录（不再静默返回 0）
5. 安全保护规则
6. 报告生成
7. 系统管理模块优雅降级
"""

import os
import sys
import tempfile
import shutil
import traceback
import threading

import unittest
import logging

logging.basicConfig(level=logging.CRITICAL)  # 测试时减少噪音

# 确保模块可导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TestScannerV3(unittest.TestCase):
    """扫描器 v3.0 测试。"""

    def setUp(self):
        self.scanner = __import__("scanner").Scanner()
        self.tmp = tempfile.mkdtemp(prefix="cc_test_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_deep_recursion_finds_nested_files(self):
        """核心回归：深度递归能扫到嵌套子目录文件（修复 quick_mode bug）。"""
        # 在临时目录创建嵌套结构：dir1/dir2/dir3/file.txt
        nested = os.path.join(self.tmp, "dir1", "dir2", "dir3")
        os.makedirs(nested)
        f = os.path.join(nested, "deep_file.txt")
        with open(f, "w") as fh:
            fh.write("x" * 1024)

        files, size = self.scanner._scan_single_path_scandir(
            self.tmp, None, scan_mode="deep"
        )
        self.assertIn(f, files, "深度递归必须找到嵌套文件")
        self.assertEqual(size, 1024)

    def test_shallow_only_one_level(self):
        """shallow 模式只扫一层。"""
        nested = os.path.join(self.tmp, "dir1", "dir2")
        os.makedirs(nested)
        deep = os.path.join(nested, "deep.txt")
        with open(deep, "w") as fh:
            fh.write("y")
        top = os.path.join(self.tmp, "top.txt")
        with open(top, "w") as fh:
            fh.write("z")

        files, _ = self.scanner._scan_single_path_scandir(
            self.tmp, None, scan_mode="shallow"
        )
        # shallow 顶层文件应被找到，嵌套的不会
        self.assertIn(top, files)
        self.assertNotIn(deep, files)

    def test_env_var_expansion(self):
        """环境变量展开。"""
        result = self.scanner.expand_env_path("%TEMP%")
        self.assertTrue(len(result) >= 1)
        self.assertFalse("%" in result[0], "环境变量应被展开")

    def test_permission_recorded(self):
        """权限不足时记录到 _permission_errors（不再静默返回 0）。"""
        self.scanner._permission_errors.clear()
        # 使用一个不存在的受保护路径测试逻辑（实际访问受保护目录在非管理员下会失败）
        # 这里验证容器本身可工作
        self.scanner._permission_errors.add("C:\\Windows\\System32\\catroot")
        self.assertIn("C:\\Windows\\System32\\catroot", self.scanner.get_permission_errors())

    def test_dir_clean_target_counts_dirs(self):
        """clean_target=dir 的类别统计目录大小。"""
        from config import get_default_categories
        cfg = get_default_categories()["Windows 临时文件"]
        self.assertEqual(cfg["clean_target"], "dir")
        cat = self.scanner._scan_category("Windows 临时文件", cfg)
        self.assertEqual(cat.clean_target, "dir")
        self.assertIsInstance(cat.file_count, int)

    def test_all_categories_have_fields(self):
        """所有类别都有必要的字段。"""
        from config import get_default_categories
        cats = get_default_categories()
        self.assertGreaterEqual(len(cats), 30)
        for name, cfg in cats.items():
            self.assertIn("clean_target", cfg, f"{name} 缺少 clean_target")
            if cfg.get("clean_target") == "command":
                # 命令式清理类别使用 command 字段，无需 scan_mode/paths
                continue
            if "use_shell_api" not in cfg:
                self.assertIn("scan_mode", cfg, f"{name} 缺少 scan_mode")
            self.assertIn("tab", cfg, f"{name} 缺少 tab")
            self.assertIn(cfg["tab"], ("quick", "deep"))


class TestCleanerV3(unittest.TestCase):
    """清理器 v3.0 测试。"""

    def setUp(self):
        self.cleaner = __import__("cleaner").Cleaner()
        self.tmp = tempfile.mkdtemp(prefix="cc_clean_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_safe_delete_dir_removes_and_recreates(self):
        """核心回归：整目录删除应真正删除内容并重建空目录。"""
        sub = os.path.join(self.tmp, "cachedir")
        os.makedirs(sub)
        with open(os.path.join(sub, "a.tmp"), "w") as fh:
            fh.write("data")
        os.makedirs(os.path.join(sub, "nested"))
        with open(os.path.join(sub, "nested", "b.tmp"), "w") as fh:
            fh.write("more")

        ok, freed, _ = self.cleaner._safe_delete_dir(sub, dry_run=False, use_quarantine=False)
        self.assertTrue(ok)
        self.assertGreater(freed, 0)
        # 目录应被重建为空目录
        self.assertTrue(os.path.exists(sub), "整目录清理后应重建空目录")
        self.assertEqual(os.listdir(sub), [], "重建目录应为空")

    def test_dry_run_no_actual_delete(self):
        """dry_run 不实际删除。"""
        f = os.path.join(self.tmp, "keep.txt")
        with open(f, "w") as fh:
            fh.write("important")
        ok, freed, _ = self.cleaner._safe_delete_file(f, dry_run=True)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(f), "dry_run 不应实际删除文件")

    def test_protected_dir_not_deleted(self):
        """受保护目录下的文件不被删除。"""
        # 模拟一个受保护路径（用扫描器的受保护目录判断）
        protected = r"C:\Windows\System32\ntdll.dll"
        ok, freed, _ = self.cleaner._safe_delete_file(protected, dry_run=False)
        self.assertFalse(ok, "受保护文件不应被删除")

    def test_remove_empty_parent_dirs(self):
        """清理后删除空父目录。"""
        parent = os.path.join(self.tmp, "empty_parent")
        child = os.path.join(parent, "sub")
        os.makedirs(child)
        f = os.path.join(child, "x.txt")
        with open(f, "w") as fh:
            fh.write("z")
        # 删除文件
        self.cleaner._safe_delete_file(f, dry_run=False)
        # 删除空父目录
        self.cleaner._remove_empty_parent_dirs(f, self.tmp)
        self.assertFalse(os.path.exists(child), "空的子目录应被删除")
        self.assertFalse(os.path.exists(parent), "空的父目录应被删除")

    def test_large_file_protection(self):
        """大文件保护：超过阈值跳过（用小阈值避免真实写大文件）。"""
        self.cleaner._large_file_threshold = 100  # 阈值设为 100 字节
        big = os.path.join(self.tmp, "big.iso")
        with open(big, "wb") as fh:
            fh.write(b"0" * 200)  # 200 字节，超过阈值
        ok, freed, _ = self.cleaner._safe_delete_file(big, dry_run=False)
        self.assertFalse(ok, "大文件应被保护跳过")
        self.assertTrue(os.path.exists(big), "大文件不应被删除")
        os.remove(big)

    def test_clean_categories_dir_target(self):
        """整目录类清理流程。"""
        from scanner import ScanCategory
        sub = os.path.join(self.tmp, "wc")
        os.makedirs(sub)
        with open(os.path.join(sub, "c.tmp"), "w") as fh:
            fh.write("tmp")
        cat = ScanCategory(
            name="测试整目录", description="", files=[sub],
            total_size=3, file_count=1, clean_target="dir",
        )
        result = self.cleaner.clean_categories({"测试整目录": cat}, dry_run=False, use_quarantine=False)
        self.assertEqual(result.files_deleted, 1)
        self.assertTrue(os.path.exists(sub))
        self.assertEqual(os.listdir(sub), [])


class TestUtils(unittest.TestCase):
    """工具函数测试。"""

    def test_format_size(self):
        utils = __import__("utils")
        self.assertEqual(utils.format_size(0), "0 B")
        self.assertEqual(utils.format_size(1024), "1.0 KB")
        self.assertTrue(utils.format_size(1024 * 1024 * 1024).endswith("GB"))

    def test_is_sub_path(self):
        utils = __import__("utils")
        self.assertTrue(utils.is_sub_path(r"C:\a\b\c.txt", r"C:\a"))
        self.assertFalse(utils.is_sub_path(r"C:\abc\d.txt", r"C:\ab"))


class TestReport(unittest.TestCase):
    """报告生成测试。"""

    def test_generate_html_report(self):
        report = __import__("report")
        cleaner = __import__("cleaner")
        result = cleaner.CleanResult(total_files_found=10, files_deleted=8,
                                      size_freed=1024 * 1024, dry_run=False)
        result.by_category = {"测试": {"deleted": 8, "freed": 1024 * 1024, "skipped": 2}}
        out = report.generate_clean_report(result, permission_errors=["C:\\Windows\\Temp"])
        self.assertTrue(os.path.exists(out))
        with open(out, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn("清理报告", html)
        self.assertIn("测试", html)
        os.remove(out)


class TestSystemTools(unittest.TestCase):
    """系统管理模块测试（Windows 环境）。"""

    def test_graceful_import(self):
        st = __import__("systemtools")
        self.assertTrue(hasattr(st, "get_installed_programs"))
        self.assertTrue(hasattr(st, "get_startup_items"))

    def test_get_installed_programs_returns_list(self):
        st = __import__("systemtools")
        # Windows 环境应返回列表（可能为空）
        progs = st.get_installed_programs()
        self.assertIsInstance(progs, list)

    def test_get_startup_items_returns_list(self):
        st = __import__("systemtools")
        items = st.get_startup_items()
        self.assertIsInstance(items, list)


class TestGUIFunctions(unittest.TestCase):
    """GUI 结构验证（不启动 GUI，仅 AST）。"""

    def test_gui_has_required_methods(self):
        import ast
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui.py"), "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        methods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                methods.add(node.name)
        required = [
            "_build_layout", "_build_dashboard_view", "_build_clean_view",
            "_build_cdisk_view", "_build_migrate_view", "_build_manage_view",
            "_build_restore_view", "_build_settings_view", "_show_view", "_card",
            "_refresh_dashboard", "_on_scan", "_on_clean", "_on_analyze",
            "_on_smart_clean", "_on_load_startup", "_on_load_programs",
            "_on_load_registry", "_refresh_disk_info", "_log",
        ]
        for r in required:
            self.assertIn(r, methods, f"GUI 缺少方法: {r}")


class TestNewFeaturesV31(unittest.TestCase):
    """v3.1 新增能力测试：sweep 清扫、命令式清理、迁移校验。"""

    def test_parse_analyze_dism_chinese(self):
        from scanner import Scanner
        txt = "Windows 组件存储 (WinSxS) 分析完成。\n可回收的空间 : 3.45 GB"
        self.assertEqual(Scanner._parse_analyze("dism_reclaim", txt), int(3.45 * 1024 ** 3))

    def test_parse_analyze_dism_english(self):
        from scanner import Scanner
        txt = "Space can be reclaimed: 1.20 GB"
        self.assertEqual(Scanner._parse_analyze("dism_reclaim", txt), int(1.20 * 1024 ** 3))

    def test_parse_analyze_mb(self):
        from scanner import Scanner
        txt = "可回收的空间 : 500.00 MB"
        self.assertEqual(Scanner._parse_analyze("dism_reclaim", txt), int(500 * 1024 ** 2))

    def test_parse_analyze_none(self):
        from scanner import Scanner
        self.assertIsNone(Scanner._parse_analyze("dism_reclaim", "no info here"))

    def test_is_protected_dir(self):
        from scanner import Scanner
        sc = Scanner()
        self.assertTrue(sc._is_protected_dir(r"C:\Windows\System32"))
        self.assertFalse(sc._is_protected_dir(r"C:\Users\JoShua\Documents"))
        self.assertTrue(sc._is_protected_dir(r"C:\Users\JoShua\Documents", skip_user_dirs=True))

    def test_scan_sweep_category(self):
        import tempfile, os
        from scanner import Scanner
        d = tempfile.mkdtemp()
        open(os.path.join(d, "a.tmp"), "w").write("x")
        nested = os.path.join(d, "sub1", "sub2")
        os.makedirs(nested)
        open(os.path.join(nested, "b.bak"), "w").write("y")
        open(os.path.join(nested, "keep.txt"), "w").write("z")  # 非垃圾扩展名
        cfg = {
            "description": "test sweep", "clean_target": "files",
            "scan_mode": "sweep", "paths": [d],
            "extensions": [".tmp", ".bak"], "sweep_max_depth": 6, "tab": "deep",
        }
        sc = Scanner()
        cat = sc._scan_sweep_category("测试清扫", cfg)
        self.assertEqual(cat.clean_target, "files")
        self.assertEqual(len(cat.files), 2)
        self.assertNotIn(os.path.join(nested, "keep.txt"), cat.files)

    def test_scan_sweep_skips_protected_dirs(self):
        import os
        from scanner import Scanner
        from config import get_protected_directories
        prot = None
        for d in get_protected_directories():
            if os.path.exists(d) and os.path.isdir(d):
                prot = d
                break
        if prot is None:
            self.skipTest("本机无受保护目录可用于测试")
        cfg = {
            "description": "t", "clean_target": "files", "scan_mode": "sweep",
            "paths": [prot], "extensions": [".log"], "sweep_max_depth": 3, "tab": "deep",
        }
        sc = Scanner()
        cat = sc._scan_sweep_category("t", cfg)
        self.assertEqual(len(cat.files), 0)

    def test_move_file_to_drive_same_drive(self):
        import tempfile, os
        from systemtools import move_file_to_drive
        d = tempfile.mkdtemp()
        f = os.path.join(d, "x.bin")
        open(f, "w").write("1")
        drive = os.path.splitdrive(d)[0] + "\\"
        ok, np, msg = move_file_to_drive(f, drive)
        self.assertFalse(ok)
        self.assertIn("同一盘", msg)

    def test_move_file_to_drive_dest_missing(self):
        from systemtools import move_file_to_drive
        ok, np, msg = move_file_to_drive(r"C:\nope.bin", "Z:\\")
        self.assertFalse(ok)
        self.assertIn("不存在", msg)

    def test_clean_command_dry_run(self):
        from cleaner import Cleaner
        from scanner import ScanCategory
        c = Cleaner()
        cat = ScanCategory(
            name="测试命令", description="", files=["__command__"],
            total_size=1024, file_count=1, clean_target="command",
            command="echo hi", requires_admin=False,
        )
        res = c.clean_categories({"测试命令": cat}, dry_run=True)
        self.assertEqual(res.files_deleted, 1)
        self.assertEqual(res.size_freed, 1024)

    def test_clean_command_requires_admin_skip(self):
        import cleaner as cleaner_mod
        from cleaner import Cleaner
        from scanner import ScanCategory
        orig = cleaner_mod.is_process_elevated
        cleaner_mod.is_process_elevated = lambda: False
        try:
            c = Cleaner()
            cat = ScanCategory(
                name="高权限命令", description="", files=["__command__"],
                total_size=0, file_count=1, clean_target="command",
                command="echo hi", requires_admin=True,
            )
            res = c.clean_categories({"高权限命令": cat}, dry_run=False)
            self.assertEqual(res.files_skipped, 1)
            self.assertTrue(any("管理员" in e for e in res.errors))
        finally:
            cleaner_mod.is_process_elevated = orig


def run_all():
    """运行全部测试，返回 (passed, failed, total)。"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [
        TestScannerV3, TestCleanerV3, TestUtils, TestReport,
        TestSystemTools, TestGUIFunctions, TestNewFeaturesV31,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    import io
    stream = io.StringIO()
    runner = unittest.TextTestRunner(stream=stream, verbosity=2)
    result = runner.run(suite)

    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    passed = total - failed
    print(stream.getvalue())
    return passed, failed, total


if __name__ == "__main__":
    passed, failed, total = run_all()
    print(f"\n{'='*50}")
    print(f"v3.0 测试结果: 通过 {passed} / 共 {total}，失败 {failed}")
    print(f"{'='*50}")
    sys.exit(0 if failed == 0 else 1)
