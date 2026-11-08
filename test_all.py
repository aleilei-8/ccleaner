# -*- coding: utf-8 -*-
"""C盘清理大师 - 综合测试套件

测试覆盖：
1. 语法和导入检查
2. 配置模块 (config.py)
3. 扫描器模块 (scanner.py)
4. 清理器模块 (cleaner.py)
5. 工具函数模块 (utils.py)
6. GUI 模块结构验证 (gui.py)
"""

import sys
import os
import json
import shutil
import tempfile
import traceback

# 确保项目根目录在 sys.path 中
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)


# ======================== 测试框架 ========================

class TestResult:
    """单个测试结果。"""
    def __init__(self, name, passed, message=""):
        self.name = name
        self.passed = passed
        self.message = message


class TestRunner:
    """简易测试运行器。"""
    def __init__(self):
        self.results = []

    def add(self, name, passed, message=""):
        self.results.append(TestResult(name, passed, message))
        status = "PASS" if passed else "FAIL"
        msg = f"  [{status}] {name}"
        if message:
            msg += f" — {message}"
        print(msg)

    def summary(self):
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed
        print(f"\n{'='*60}")
        print(f"测试完成: {total} 个测试 | 通过: {passed} | 失败: {failed}")
        print(f"{'='*60}")
        return self.results


def assert_equal(runner, test_name, actual, expected):
    """断言相等。"""
    if actual == expected:
        runner.add(test_name, True)
    else:
        runner.add(test_name, False, f"Expected {expected!r}, Got {actual!r}")


def assert_true(runner, test_name, value, message=""):
    """断言为 True。"""
    if value:
        runner.add(test_name, True)
    else:
        runner.add(test_name, False, message or f"Expected True, Got {value!r}")


def assert_false(runner, test_name, value, message=""):
    """断言为 False。"""
    if not value:
        runner.add(test_name, True)
    else:
        runner.add(test_name, False, message or f"Expected False, Got {value!r}")


def assert_not_raise(runner, test_name, func, *args, **kwargs):
    """断言不抛出异常。"""
    try:
        func(*args, **kwargs)
        runner.add(test_name, True)
    except Exception as e:
        runner.add(test_name, False, f"Raised {type(e).__name__}: {e}")


def assert_greater_than(runner, test_name, actual, threshold, message=""):
    """断言大于。"""
    if actual > threshold:
        runner.add(test_name, True)
    else:
        runner.add(test_name, False, message or f"Expected > {threshold}, Got {actual}")


def assert_contains(runner, test_name, collection, item, message=""):
    """断言包含。"""
    if item in collection:
        runner.add(test_name, True)
    else:
        runner.add(test_name, False, message or f"Expected {item!r} in collection")


def assert_type(runner, test_name, value, expected_type, message=""):
    """断言类型。"""
    if isinstance(value, expected_type):
        runner.add(test_name, True)
    else:
        runner.add(test_name, False, message or f"Expected {expected_type.__name__}, Got {type(value).__name__}")


def assert_length(runner, test_name, collection, expected_len, message=""):
    """断言长度。"""
    if len(collection) == expected_len:
        runner.add(test_name, True)
    else:
        runner.add(test_name, False, message or f"Expected length {expected_len}, Got {len(collection)}")


# ======================== 1. 语法和导入检查 ========================

def test_syntax_and_imports(runner):
    """测试所有模块的语法正确性和导入。"""
    print("\n--- 1. 语法和导入检查 ---")

    py_files = [
        "config.py", "scanner.py", "cleaner.py",
        "utils.py", "gui.py", "main.py"
    ]

    # py_compile 检查
    import py_compile
    for fname in py_files:
        fpath = os.path.join(PROJECT_DIR, fname)
        try:
            py_compile.compile(fpath, doraise=True)
            runner.add(f"语法检查: {fname}", True)
        except py_compile.PyCompileError as e:
            runner.add(f"语法检查: {fname}", False, str(e))

    # 模块导入检查
    modules_to_test = [
        ("config", "config"),
        ("utils", "utils"),
        ("scanner", "scanner"),
        ("cleaner", "cleaner"),
    ]

    for module_name, import_name in modules_to_test:
        try:
            __import__(import_name)
            runner.add(f"导入检查: {module_name}", True)
        except Exception as e:
            runner.add(f"导入检查: {module_name}", False, str(e))


# ======================== 2. 配置模块测试 (config.py) ========================

def test_config_module(runner):
    """测试配置模块。"""
    print("\n--- 2. 配置模块测试 ---")

    from config import (
        get_default_categories,
        get_protected_directories,
        get_protected_extensions_in_windows,
        get_protected_files,
        get_protected_user_dirs,
        Config,
    )

    # 2.1 测试清理类别数量（预期 11 个）
    categories = get_default_categories()
    assert_length(runner, "CLEAN_CATEGORIES 包含 11 个类别", categories, 11)

    # 2.2 验证所有 11 个类别名称
    expected_category_names = [
        "Windows 临时文件", "回收站", "Chrome 浏览器缓存",
        "Edge 浏览器缓存", "Firefox 浏览器缓存", "Windows 更新缓存",
        "预读取文件", "缩略图缓存", "Windows 错误报告",
        "DirectX 着色器缓存", "传递优化文件",
    ]
    for name in expected_category_names:
        assert_contains(runner, f"类别存在: {name}", categories, name)

    # 2.3 每个类别必须有 paths 和 description
    for cat_name, cat_config in categories.items():
        assert_contains(runner, f"类别 {cat_name} 有 paths", cat_config, "paths")
        assert_true(runner, f"类别 {cat_name} paths 非空", len(cat_config["paths"]) > 0)
        assert_contains(runner, f"类别 {cat_name} 有 description", cat_config, "description")

    # 2.4 测试受保护目录
    protected_dirs = get_protected_directories()
    assert_type(runner, "PROTECTED_DIRS 是 set", protected_dirs, set)
    assert_greater_than(runner, "PROTECTED_DIRS 非空", len(protected_dirs), 0)

    # 验证关键受保护目录
    critical_dirs = ["system32", "syswow64", "program files", "programdata"]
    for keyword in critical_dirs:
        found = any(keyword in d for d in protected_dirs)
        assert_true(runner, f"PROTECTED_DIRS 包含 {keyword}", found)

    # 2.5 测试受保护文件
    protected_files = get_protected_files()
    assert_type(runner, "PROTECTED_FILES 是 set", protected_files, set)
    assert_greater_than(runner, "PROTECTED_FILES 非空", len(protected_files), 0)

    # 验证引导文件
    critical_files = ["bootmgr", "ntoskrnl.exe", "hal.dll"]
    for keyword in critical_files:
        found = any(keyword in f for f in protected_files)
        assert_true(runner, f"PROTECTED_FILES 包含 {keyword}", found)

    # 2.6 测试受保护扩展名
    protected_exts = get_protected_extensions_in_windows()
    assert_type(runner, "PROTECTED_EXTENSIONS 是 set", protected_exts, set)
    assert_greater_than(runner, "PROTECTED_EXTENSIONS 非空", len(protected_exts), 0)

    for ext in [".dll", ".sys", ".exe", ".drv", ".inf", ".msi"]:
        assert_contains(runner, f"PROTECTED_EXTENSIONS 包含 {ext}", protected_exts, ext)

    # 2.7 测试受保护用户目录
    user_dirs = get_protected_user_dirs()
    assert_type(runner, "PROTECTED_USER_DIRS 是 list", user_dirs, list)
    for d in ["Documents", "Desktop", "Pictures", "Downloads"]:
        assert_contains(runner, f"PROTECTED_USER_DIRS 包含 {d}", user_dirs, d)

    # 2.8 测试 Config 类
    with tempfile.TemporaryDirectory() as tmpdir:
        config_file = os.path.join(tmpdir, "test_config.json")
        cfg = Config(config_file)

        # 默认值
        assert_false(runner, "Config 默认 auto_clean=False", cfg.auto_clean)
        assert_equal(runner, "Config 默认 auto_clean_interval=24", cfg.auto_clean_interval_hours, 24)
        assert_equal(runner, "Config 默认 theme=dark", cfg.theme, "dark")
        assert_true(runner, "Config 默认 minimize_to_tray=True", cfg.minimize_to_tray)

        # 设置值
        cfg.auto_clean = True
        assert_true(runner, "Config 设置 auto_clean=True 后读取", cfg.auto_clean)

        cfg.theme = "light"
        assert_equal(runner, "Config 设置 theme=light 后读取", cfg.theme, "light")

        cfg.auto_clean_interval_hours = 48
        assert_equal(runner, "Config 设置 interval=48 后读取", cfg.auto_clean_interval_hours, 48)

        # 验证文件已保存
        assert_true(runner, "Config 文件已保存", os.path.exists(config_file))

        # 验证文件内容正确
        with open(config_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert_equal(runner, "Config 文件 auto_clean=True", data.get("auto_clean"), True)
        assert_equal(runner, "Config 文件 theme=light", data.get("theme"), "light")

    # 2.9 测试 Config 加载已有配置
    with tempfile.TemporaryDirectory() as tmpdir:
        config_file = os.path.join(tmpdir, "test_config2.json")
        # 写入自定义配置
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump({"auto_clean": True, "theme": "blue", "minimize_to_tray": False}, f)
        cfg = Config(config_file)
        assert_true(runner, "Config 加载已有配置 auto_clean=True", cfg.auto_clean)
        assert_equal(runner, "Config 加载已有配置 theme=blue", cfg.theme, "blue")
        assert_false(runner, "Config 加载已有配置 minimize_to_tray=False", cfg.minimize_to_tray)

    # 2.10 测试 Config 处理损坏的 JSON
    with tempfile.TemporaryDirectory() as tmpdir:
        config_file = os.path.join(tmpdir, "test_config3.json")
        with open(config_file, "w") as f:
            f.write("{invalid json")
        cfg = Config(config_file)
        assert_false(runner, "Config 损坏 JSON 回退默认值 auto_clean=False", cfg.auto_clean)


# ======================== 3. 扫描器测试 (scanner.py) ========================

def test_scanner_module(runner):
    """测试扫描器模块。"""
    print("\n--- 3. 扫描器模块测试 ---")

    from scanner import Scanner, ScanCategory
    from config import get_protected_directories

    # 3.1 创建 Scanner 实例
    assert_not_raise(runner, "Scanner 实例化", Scanner)

    scanner = Scanner()

    # 3.2 测试 ScanCategory 数据类
    cat = ScanCategory(
        name="测试类别",
        description="测试描述",
        files=["/tmp/a.txt", "/tmp/b.txt"],
        total_size=2048,
        file_count=2,
        enabled=True,
    )
    assert_equal(runner, "ScanCategory name", cat.name, "测试类别")
    assert_equal(runner, "ScanCategory file_count", cat.file_count, 2)
    assert_equal(runner, "ScanCategory total_size", cat.total_size, 2048)
    assert_true(runner, "ScanCategory enabled", cat.enabled)

    # 3.3 测试默认 ScanCategory
    default_cat = ScanCategory(name="默认", description="")
    assert_equal(runner, "ScanCategory 默认 files 为空列表", default_cat.files, [])
    assert_equal(runner, "ScanCategory 默认 total_size=0", default_cat.total_size, 0)
    assert_equal(runner, "ScanCategory 默认 file_count=0", default_cat.file_count, 0)
    assert_true(runner, "ScanCategory 默认 enabled=True", default_cat.enabled)

    # 3.4 测试保护检查 - System32 下文件应受保护
    assert_true(runner, "_is_protected: System32 下文件受保护",
                scanner._is_protected(r"C:\Windows\System32\kernel32.dll"))

    # 3.5 测试保护检查 - SysWOW64 下文件应受保护
    assert_true(runner, "_is_protected: SysWOW64 下文件受保护",
                scanner._is_protected(r"C:\Windows\SysWOW64\kernel32.dll"))

    # 3.6 测试保护检查 - Program Files 下文件应受保护
    assert_true(runner, "_is_protected: Program Files 下文件受保护",
                scanner._is_protected(r"C:\Program Files\app\app.exe"))

    # 3.7 测试保护检查 - 引导文件受保护
    assert_true(runner, "_is_protected: bootmgr 受保护",
                scanner._is_protected(r"C:\bootmgr"))
    assert_true(runner, "_is_protected: ntoskrnl.exe 受保护",
                scanner._is_protected(r"C:\Windows\System32\ntoskrnl.exe"))

    # 3.8 测试保护检查 - Windows 目录下 .dll 受保护
    assert_true(runner, "_is_protected: Windows 下 .dll 受保护",
                scanner._is_protected(r"C:\Windows\some\test.dll"))

    # 3.9 测试保护检查 - Windows 目录下 .sys 受保护
    assert_true(runner, "_is_protected: Windows 下 .sys 受保护",
                scanner._is_protected(r"C:\Windows\System32\drivers\test.sys"))

    # 3.10 测试保护检查 - 非 Windows 目录下 .dll 不受保护
    assert_false(runner, "_is_protected: 非 Windows 目录下 .dll 不受保护",
                 scanner._is_protected(r"C:\Users\Test\app\test.dll"))

    # 3.11 测试保护检查 - TEMP 目录下文件不受保护
    temp_dir = os.environ.get("TEMP", "")
    if temp_dir:
        assert_false(runner, "_is_protected: TEMP 下文件不受保护",
                     scanner._is_protected(os.path.join(temp_dir, "test.tmp")))

    # 3.12 测试 _is_windows_dir
    assert_true(runner, "_is_windows_dir: C:\\Windows",
                scanner._is_windows_dir(r"C:\Windows\System32"))
    assert_true(runner, "_is_windows_dir: C:\\Windows 根",
                scanner._is_windows_dir(r"C:\Windows"))
    assert_false(runner, "_is_windows_dir: C:\\Users",
                 scanner._is_windows_dir(r"C:\Users\Test"))

    # 3.13 测试扫描不存在的目录
    result = scanner._scan_single_path(r"C:\NonExistent\Directory\12345")
    assert_equal(runner, "扫描不存在的目录返回空列表", result, [])

    # 3.14 测试扫描实际 TEMP 目录（验证结构不崩溃）
    temp_dir = os.environ.get("TEMP", "")
    if temp_dir and os.path.exists(temp_dir):
        files = scanner._scan_single_path(temp_dir)
        assert_type(runner, "扫描 TEMP 返回 list", files, list)

    # 3.15 测试 _scan_category 结构
    cat_config = {
        "paths": [r"C:\NonExistent\Path"],
        "description": "测试类别",
    }
    cat_result = scanner._scan_category("测试", cat_config)
    assert_type(runner, "_scan_category 返回 ScanCategory", cat_result, ScanCategory)
    assert_equal(runner, "_scan_category name", cat_result.name, "测试")
    assert_equal(runner, "_scan_category description", cat_result.description, "测试类别")
    assert_equal(runner, "_scan_category file_count (空目录)", cat_result.file_count, 0)
    assert_equal(runner, "_scan_category total_size (空目录)", cat_result.total_size, 0)

    # 3.16 测试进度回调
    progress_data = []
    def progress_cb(current, total, name):
        progress_data.append((current, total, name))

    scanner.set_progress_callback(progress_cb)
    scanner._report_progress(1, 10, "测试")
    assert_equal(runner, "进度回调被调用", len(progress_data), 1)
    assert_equal(runner, "进度回调数据正确", progress_data[0], (1, 10, "测试"))

    # 3.17 测试异常回调不崩溃
    def bad_callback(current, total, name):
        raise ValueError("test error")

    scanner.set_progress_callback(bad_callback)
    assert_not_raise(runner, "异常进度回调不导致崩溃",
                     scanner._report_progress, 1, 10, "测试")

    # 3.18 测试 is_scanning 属性
    assert_false(runner, "初始 is_scanning=False", scanner.is_scanning)

    # 3.19 测试扩展名过滤（Bug 1 回归验证）
    # FIXED: scanner.py now uses os.path.splitext for exact extension matching
    # and fnmatch only for wildcard patterns (containing "*").
    with tempfile.TemporaryDirectory() as tmpdir:
        for fname in ["test.cache", "test.sqlite-wal", "readme.txt"]:
            with open(os.path.join(tmpdir, fname), "w") as f:
                f.write("x" * 100)
        # After fix: ".cache" should match "test.cache" via splitext comparison
        result = scanner._scan_single_path(tmpdir, extensions=[".cache"])
        assert_length(runner, "扩展名过滤: .cache 精确匹配 test.cache", result, 1)
        assert_true(runner, "扩展名过滤: 匹配到正确文件 test.cache",
                    result[0].endswith("test.cache"))

    # 3.19b 测试多种简单扩展名同时过滤
    with tempfile.TemporaryDirectory() as tmpdir:
        for fname in ["a.cache", "b.sqlite-wal", "c.sqlite-shm", "d.txt"]:
            with open(os.path.join(tmpdir, fname), "w") as f:
                f.write("x" * 100)
        result = scanner._scan_single_path(tmpdir, extensions=[".cache", ".sqlite-wal"])
        assert_length(runner, "扩展名过滤: 多个精确扩展名匹配 2 个", result, 2)
        matched_names = [os.path.basename(f) for f in result]
        assert_true(runner, "扩展名过滤: 包含 a.cache", "a.cache" in matched_names)
        assert_true(runner, "扩展名过滤: 包含 b.sqlite-wal", "b.sqlite-wal" in matched_names)

    # 3.19c 测试通配符扩展名过滤
    with tempfile.TemporaryDirectory() as tmpdir:
        for fname in ["thumbcache_32.db", "thumbcache_256.db", "other.db"]:
            with open(os.path.join(tmpdir, fname), "w") as f:
                f.write("x" * 100)
        result = scanner._scan_single_path(tmpdir, extensions=["thumbcache_*.db"])
        assert_length(runner, "通配符过滤: thumbcache_*.db 匹配 2 个", result, 2)

    # 3.19d 测试精确扩展名和通配符混合过滤
    with tempfile.TemporaryDirectory() as tmpdir:
        for fname in ["test.cache", "thumbcache_32.db", "other.db", "data.log"]:
            with open(os.path.join(tmpdir, fname), "w") as f:
                f.write("x" * 100)
        result = scanner._scan_single_path(tmpdir, extensions=[".cache", "thumbcache_*.db"])
        assert_length(runner, "混合过滤: .cache + thumbcache_*.db 匹配 2 个", result, 2)

    # 3.21 测试 scan_categories（指定类别扫描）
    assert_not_raise(runner, "scan_categories 不崩溃",
                     scanner.scan_categories, ["Windows 临时文件"])


# ======================== 4. 清理器测试 (cleaner.py) ========================

def test_cleaner_module(runner):
    """测试清理器模块。"""
    print("\n--- 4. 清理器模块测试 ---")

    from cleaner import Cleaner, CleanResult, AutoCleaner
    from scanner import ScanCategory

    # 4.1 创建 Cleaner 实例
    assert_not_raise(runner, "Cleaner 实例化", Cleaner)
    cleaner = Cleaner()

    # 4.2 CleanResult 数据类
    result = CleanResult(
        total_files_found=100, total_size_found=1048576,
        files_deleted=80, size_freed=838860,
        files_skipped=20, errors=["error1"]
    )
    assert_equal(runner, "CleanResult total_files_found", result.total_files_found, 100)
    assert_equal(runner, "CleanResult files_deleted", result.files_deleted, 80)
    assert_equal(runner, "CleanResult files_skipped", result.files_skipped, 20)
    assert_length(runner, "CleanResult errors", result.errors, 1)

    # 4.3 CleanResult summary() 方法
    summary = result.summary()
    assert_true(runner, "CleanResult.summary() 包含 '清理完成'", "清理完成" in summary)
    assert_true(runner, "CleanResult.summary() 包含文件数", "100" in summary)

    # 4.4 CleanResult 默认 errors=None
    default_result = CleanResult()
    assert_equal(runner, "CleanResult 默认 errors=[]", default_result.errors, [])

    # 4.5 安全保护 - System32 下文件不应被删除
    assert_true(runner, "Cleaner._is_protected: System32",
                cleaner._is_protected(r"C:\Windows\System32\kernel32.dll"))

    # 4.6 安全保护 - .sys 文件在 Windows 下受保护
    assert_true(runner, "Cleaner._is_protected: Windows 下 .sys",
                cleaner._is_protected(r"C:\Windows\System32\drivers\acpi.sys"))

    # 4.7 安全保护 - 引导文件受保护
    assert_true(runner, "Cleaner._is_protected: bootmgr",
                cleaner._is_protected(r"C:\bootmgr"))
    assert_true(runner, "Cleaner._is_protected: BCD",
                cleaner._is_protected(r"C:\BCD"))

    # 4.8 安全保护 - 非 Windows 目录 .dll 不受保护
    assert_false(runner, "Cleaner._is_protected: 非 Windows .dll",
                 cleaner._is_protected(r"C:\Users\Test\app\test.dll"))

    # 4.9 测试 _safe_delete_file 对受保护文件不删除
    # (不实际删除，只验证逻辑路径)
    protected_ret = cleaner._safe_delete_file(r"C:\Windows\System32\ntoskrnl.exe")
    assert_equal(runner, "_safe_delete_file 保护 System32 文件", protected_ret, (False, 0))

    protected_ret2 = cleaner._safe_delete_file(r"C:\bootmgr")
    assert_equal(runner, "_safe_delete_file 保护 bootmgr", protected_ret2, (False, 0))

    # 4.10 测试 _safe_delete_file 对不存在文件
    ret = cleaner._safe_delete_file(r"C:\NonExistent\File\12345.txt")
    assert_equal(runner, "_safe_delete_file 不存在文件返回 (False, 0)", ret, (False, 0))

    # 4.11 测试 clean_categories 空列表
    empty_result = cleaner.clean_categories({})
    assert_type(runner, "clean_categories 空字典返回 CleanResult", empty_result, CleanResult)
    assert_equal(runner, "clean_categories 空字典 files_deleted=0", empty_result.files_deleted, 0)

    # 4.12 测试 clean_categories 全 disabled
    disabled_cat = ScanCategory(
        name="测试", description="测试", files=["/tmp/test.txt"],
        total_size=100, file_count=1, enabled=False,
    )
    disabled_result = cleaner.clean_categories({"测试": disabled_cat})
    assert_equal(runner, "clean_categories disabled 类别 files_deleted=0",
                 disabled_result.files_deleted, 0)

    # 4.13 测试 clean_single_category
    enabled_cat = ScanCategory(
        name="测试", description="测试", files=[],
        total_size=0, file_count=0, enabled=True,
    )
    single_result = cleaner.clean_single_category(enabled_cat)
    assert_type(runner, "clean_single_category 返回 CleanResult", single_result, CleanResult)

    # 4.14 测试实际删除临时文件
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test_cleanup.tmp")
        with open(test_file, "w") as f:
            f.write("x" * 1000)

        assert_true(runner, "测试文件已创建", os.path.exists(test_file))

        cat = ScanCategory(
            name="测试清理", description="测试",
            files=[test_file], total_size=1000, file_count=1, enabled=True,
        )
        result = cleaner.clean_categories({"测试清理": cat})
        assert_equal(runner, "实际删除临时文件 files_deleted=1", result.files_deleted, 1)
        assert_equal(runner, "实际删除 size_freed=1000", result.size_freed, 1000)
        assert_false(runner, "文件已被删除", os.path.exists(test_file))

    # 4.15 测试取消操作（Bug 2 回归验证）
    # FIXED: clean_categories() no longer resets _cancelled at the start.
    # _cancelled = False is now in the finally block after cleaning completes.
    # Setting _cancelled = True before calling should prevent file deletion.
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test_cancel.tmp")
        with open(test_file, "w") as f:
            f.write("x" * 100)

        cleaner._cancelled = True
        cat = ScanCategory(
            name="测试取消", description="测试",
            files=[test_file], total_size=100, file_count=1, enabled=True,
        )
        result = cleaner.clean_categories({"测试取消": cat})
        # After fix: file should NOT be deleted because cancel was set
        assert_equal(runner, "取消后 files_deleted=0", result.files_deleted, 0)
        assert_true(runner, "取消后文件仍存在", os.path.exists(test_file))

    # 4.15b 测试取消状态在清理完成后正确重置
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test_cancel_reset.tmp")
        with open(test_file, "w") as f:
            f.write("x" * 100)

        cleaner._cancelled = True
        cat = ScanCategory(
            name="测试重置", description="测试",
            files=[test_file], total_size=100, file_count=1, enabled=True,
        )
        result = cleaner.clean_categories({"测试重置": cat})
        # After the cancelled clean, _cancelled should be reset to False (in finally)
        assert_false(runner, "清理完成后 _cancelled 已重置为 False", cleaner._cancelled)

    # 4.16 测试 AutoCleaner
    assert_not_raise(runner, "AutoCleaner 实例化", AutoCleaner, cleaner)

    auto = AutoCleaner(cleaner)

    # 4.17 测试 INTERVAL_PRESETS
    assert_contains(runner, "INTERVAL_PRESETS 每天", AutoCleaner.INTERVAL_PRESETS, "每天")
    assert_contains(runner, "INTERVAL_PRESETS 每周", AutoCleaner.INTERVAL_PRESETS, "每周")
    assert_contains(runner, "INTERVAL_PRESETS 每月", AutoCleaner.INTERVAL_PRESETS, "每月")
    assert_equal(runner, "INTERVAL_PRESETS 每天=24", AutoCleaner.INTERVAL_PRESETS["每天"], 24)

    # 4.18 测试 set_interval_hours
    auto.set_interval_hours(48)
    # 最小值 1
    auto.set_interval_hours(0)
    assert_equal(runner, "set_interval_hours 最小 1", auto._interval_hours, 1)

    # 4.19 测试 perform_now 无 scanner
    auto_result = auto.perform_now()
    assert_equal(runner, "perform_now 无 scanner 返回 None", auto_result, None)

    # 4.20 测试 is_cleaning 属性
    assert_false(runner, "初始 is_cleaning=False", cleaner.is_cleaning)


# ======================== 5. 工具函数测试 (utils.py) ========================

def test_utils_module(runner):
    """测试工具函数模块。"""
    print("\n--- 5. 工具函数模块测试 ---")

    from utils import (
        format_size, get_disk_usage, get_disk_usage_str,
        get_disk_usage_percent, normalize_path, is_sub_path,
        is_file_in_use, is_process_elevated, safe_remove_file,
        safe_remove_dir, setup_logging,
    )

    # 5.1 format_size 函数
    assert_equal(runner, "format_size(0)", format_size(0), "0 B")
    assert_equal(runner, "format_size(-1)", format_size(-1), "0 B")
    assert_equal(runner, "format_size(512)", format_size(512), "512.0 B")
    assert_equal(runner, "format_size(1024)", format_size(1024), "1.0 KB")
    assert_equal(runner, "format_size(1536)", format_size(1536), "1.5 KB")
    assert_equal(runner, "format_size(1048576)", format_size(1048576), "1.00 MB")
    assert_equal(runner, "format_size(1073741824)", format_size(1073741824), "1.00 GB")
    assert_equal(runner, "format_size(1099511627776)", format_size(1099511627776), "1.00 TB")

    # 5.2 get_disk_usage
    total, used, free = get_disk_usage("C:\\")
    assert_type(runner, "get_disk_usage 返回 tuple", (total, used, free), tuple)
    assert_type(runner, "get_disk_usage total 是 int", total, int)
    assert_greater_than(runner, "get_disk_usage total > 0", total, 0)
    assert_greater_than(runner, "get_disk_usage used >= 0", used, -1)
    assert_greater_than(runner, "get_disk_usage free >= 0", free, -1)

    # 5.3 get_disk_usage_str
    total_str, used_str, free_str = get_disk_usage_str("C:\\")
    assert_type(runner, "get_disk_usage_str 返回 tuple", (total_str, used_str, free_str), tuple)
    assert_type(runner, "get_disk_usage_str total 是 str", total_str, str)
    assert_true(runner, "get_disk_usage_str total 非空", len(total_str) > 0)

    # 5.4 get_disk_usage_percent
    percent = get_disk_usage_percent("C:\\")
    assert_type(runner, "get_disk_usage_percent 返回 float", percent, float)
    assert_true(runner, "get_disk_usage_percent 范围 0-100", 0.0 <= percent <= 100.0)

    # 5.5 get_disk_usage 对不存在的盘
    total2, used2, free2 = get_disk_usage("Z:\\")
    assert_equal(runner, "get_disk_usage 不存在盘返回 (0,0,0)", (total2, used2, free2), (0, 0, 0))

    # 5.6 get_disk_usage_percent 对不存在的盘
    percent2 = get_disk_usage_percent("Z:\\")
    assert_equal(runner, "get_disk_usage_percent 不存在盘返回 0.0", percent2, 0.0)

    # 5.7 normalize_path
    assert_equal(runner, "normalize_path 统一小写",
                 normalize_path(r"C:\Windows\System32"), r"c:\windows\system32")
    assert_equal(runner, "normalize_path 统一分隔符",
                 normalize_path("C:/Windows\\System32/"), r"c:\windows\system32")

    # 5.8 is_sub_path
    assert_true(runner, "is_sub_path: 子路径",
                is_sub_path(r"C:\Windows\System32\config", r"C:\Windows\System32"))
    assert_true(runner, "is_sub_path: 深层子路径",
                is_sub_path(r"C:\Windows\System32\drivers\etc\hosts",
                            r"C:\Windows\System32"))
    assert_false(runner, "is_sub_path: 非子路径",
                 is_sub_path(r"C:\Users\Test", r"C:\Windows\System32"))
    # 边界情况：不应误匹配相似名称的目录
    assert_false(runner, "is_sub_path: 不会误匹配相似名称",
                 is_sub_path(r"C:\Windows\System32Extra", r"C:\Windows\System32"))

    # 5.9 is_file_in_use 对不存在文件
    assert_false(runner, "is_file_in_use 不存在文件返回 False",
                 is_file_in_use(r"C:\NonExistent\file.txt"))

    # 5.10 is_file_in_use 对可访问文件
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".tmp") as f:
        f.write("test")
        tmp_name = f.name
    try:
        in_use = is_file_in_use(tmp_name)
        assert_type(runner, "is_file_in_use 返回 bool", in_use, bool)
    finally:
        os.unlink(tmp_name)

    # 5.11 is_process_elevated
    elevated = is_process_elevated()
    assert_type(runner, "is_process_elevated 返回 bool", elevated, bool)

    # 5.12 safe_remove_file 对不存在文件
    assert_false(runner, "safe_remove_file 不存在文件返回 False",
                 safe_remove_file(r"C:\NonExistent\file.txt"))

    # 5.13 safe_remove_file 实际删除
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".tmp") as f:
        f.write("x" * 100)
        tmp_name = f.name
    assert_true(runner, "safe_remove_file 前文件存在", os.path.exists(tmp_name))
    ret = safe_remove_file(tmp_name)
    assert_true(runner, "safe_remove_file 返回 True", ret)
    assert_false(runner, "safe_remove_file 后文件不存在", os.path.exists(tmp_name))

    # 5.14 safe_remove_dir 对不存在目录
    deleted, freed = safe_remove_dir(r"C:\NonExistent\Dir")
    assert_equal(runner, "safe_remove_dir 不存在目录返回 (0,0)", (deleted, freed), (0, 0))

    # 5.15 safe_remove_dir 实际删除
    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建文件
        for i in range(5):
            with open(os.path.join(tmpdir, f"file{i}.tmp"), "w") as f:
                f.write("x" * 200)
        # 创建子目录
        subdir = os.path.join(tmpdir, "subdir")
        os.makedirs(subdir)
        with open(os.path.join(subdir, "nested.tmp"), "w") as f:
            f.write("y" * 300)

        deleted, freed = safe_remove_dir(tmpdir)
        assert_equal(runner, "safe_remove_dir 删除 6 个文件", deleted, 6)
        assert_equal(runner, "safe_remove_dir 释放正确大小", freed, 200 * 5 + 300)

    # 5.16 setup_logging
    import logging as _logging
    log_file = None
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "test.log")
            assert_not_raise(runner, "setup_logging 不崩溃", setup_logging, log_file)
            assert_true(runner, "日志文件已创建", os.path.exists(log_file))

            # 验证日志可写入
            test_logger = _logging.getLogger("test_setup_logging")
            test_logger.info("测试日志消息")
            # 刷新 handlers
            for handler in _logging.getLogger().handlers:
                handler.flush()
            assert_true(runner, "日志文件非空",
                        os.path.getsize(log_file) > 0)
    finally:
        # 清理 logging handlers 以避免文件句柄泄漏
        root_logger = _logging.getLogger()
        for handler in root_logger.handlers[:]:
            try:
                handler.close()
            except Exception:
                pass
            root_logger.removeHandler(handler)


# ======================== 6. GUI 模块结构验证 (gui.py) ========================

def test_gui_structure(runner):
    """测试 GUI 模块的结构完整性（不做实际 GUI 渲染）。"""
    print("\n--- 6. GUI 模块结构验证 ---")

    import ast

    # 6.1 验证 gui.py 可以被 AST 解析
    gui_path = os.path.join(PROJECT_DIR, "gui.py")
    with open(gui_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    runner.add("gui.py AST 解析成功", True)

    # 6.2 查找 CleanerGUI 类
    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    class_names = [c.name for c in classes]
    assert_contains(runner, "CleanerGUI 类存在", class_names, "CleanerGUI")

    # 6.3 验证关键方法存在
    gui_class = next((c for c in classes if c.name == "CleanerGUI"), None)
    if gui_class:
        methods = [node.name for node in gui_class.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        critical_methods = [
            "_build_header", "_build_disk_info", "_build_progress_bar",
            "_build_category_list", "_build_action_buttons", "_build_result_area",
            "_build_log_area", "_build_auto_clean_section",
            "_on_scan", "_on_clean", "_on_cancel",
            "_scan_worker", "_clean_worker",
            "_on_scan_complete", "_on_clean_complete",
            "_refresh_disk_info", "_log", "_clear_log",
            "_restore_settings", "_is_admin", "destroy",
        ]
        for method_name in critical_methods:
            assert_contains(runner, f"方法存在: {method_name}", methods, method_name)
    else:
        runner.add("CleanerGUI 类未找到", False, "无法验证方法")

    # 6.4 验证颜色常量
    if gui_class:
        assignments = [node.targets[0].id for node in gui_class.body
                       if isinstance(node, ast.Assign)
                       and isinstance(node.targets[0], ast.Name)
                       and node.targets[0].id.startswith("COLOR_")]
        color_constants = ["COLOR_ACCENT", "COLOR_SUCCESS", "COLOR_WARNING",
                          "COLOR_DANGER", "COLOR_BG_DARK", "COLOR_BG_CARD"]
        for const in color_constants:
            assert_contains(runner, f"颜色常量存在: {const}", assignments, const)

    # 6.5 验证导入
    imports_found = []
    import_aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imports_found.append(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports_found.append(alias.name)
                if alias.asname:
                    import_aliases[alias.asname] = alias.name

    required_imports = ["Scanner", "ScanCategory", "Cleaner", "CleanResult",
                        "AutoCleaner", "Config"]
    for imp in required_imports:
        assert_contains(runner, f"导入存在: {imp}", imports_found, imp)
    # ctk is an alias for customtkinter
    assert_contains(runner, "导入存在: customtkinter (as ctk)", imports_found, "customtkinter")


# ======================== 7. 端到端安全验证 ========================

def test_end_to_end_safety(runner):
    """端到端安全测试：确保保护规则在扫描和清理链路中完整生效。"""
    print("\n--- 7. 端到端安全验证 ---")

    from scanner import Scanner
    from cleaner import Cleaner
    from scanner import ScanCategory

    scanner = Scanner()
    cleaner = Cleaner()

    # 7.1 关键系统文件在扫描和清理中都受保护
    critical_paths = [
        r"C:\bootmgr",
        r"C:\bootmgr.efi",
        r"C:\BCD",
        r"C:\Windows\System32\ntoskrnl.exe",
        r"C:\Windows\System32\hal.dll",
        r"C:\Windows\System32\config\SYSTEM",
        r"C:\Windows\System32\config\SAM",
    ]

    for path in critical_paths:
        scan_protected = scanner._is_protected(path)
        clean_protected = cleaner._is_protected(path)
        assert_true(runner, f"扫描保护: {os.path.basename(path)}", scan_protected)
        assert_true(runner, f"清理保护: {os.path.basename(path)}", clean_protected)

    # 7.2 受保护目录下的任意文件都应被拦截
    protected_dir_test_files = [
        r"C:\Windows\System32\config\some_file.dat",
        r"C:\Windows\SysWOW64\any_file.dll",
        r"C:\Program Files\SomeApp\app.exe",
        r"C:\Program Files (x86)\AnotherApp\app.dll",
        r"C:\ProgramData\SomeData\data.xml",
        r"C:\Windows\Installer\some.msi",
    ]

    for path in protected_dir_test_files:
        scan_protected = scanner._is_protected(path)
        clean_protected = cleaner._is_protected(path)
        assert_true(runner, f"扫描保护目录: {path}", scan_protected,
                    f"Scanner 未保护 {path}")
        assert_true(runner, f"清理保护目录: {path}", clean_protected,
                    f"Cleaner 未保护 {path}")

    # 7.3 Windows 目录下受保护扩展名
    protected_ext_files = [
        (r"C:\Windows\test.dll", ".dll"),
        (r"C:\Windows\System32\test.sys", ".sys"),
        (r"C:\Windows\test.exe", ".exe"),
        (r"C:\Windows\test.drv", ".drv"),
        (r"C:\Windows\test.inf", ".inf"),
        (r"C:\Windows\test.cat", ".cat"),
        (r"C:\Windows\test.msi", ".msi"),
    ]

    for path, ext in protected_ext_files:
        scan_protected = scanner._is_protected(path)
        clean_protected = cleaner._is_protected(path)
        assert_true(runner, f"扫描保护扩展名 {ext} in Windows", scan_protected)
        assert_true(runner, f"清理保护扩展名 {ext} in Windows", clean_protected)

    # 7.4 非 Windows 目录下不受保护扩展名
    safe_paths = [
        r"C:\Users\Test\Downloads\app.dll",
        r"C:\Temp\test.sys",
        r"C:\Users\Test\Documents\setup.exe",
    ]

    for path in safe_paths:
        scan_protected = scanner._is_protected(path)
        clean_protected = cleaner._is_protected(path)
        assert_false(runner, f"非 Windows 下不受保护 (扫描): {path}", scan_protected)
        assert_false(runner, f"非 Windows 下不受保护 (清理): {path}", clean_protected)


# ======================== 主入口 ========================

def main():
    """运行所有测试。"""
    print("=" * 60)
    print("C盘清理大师 - 综合测试套件")
    print(f"项目目录: {PROJECT_DIR}")
    print("=" * 60)

    runner = TestRunner()

    try:
        test_syntax_and_imports(runner)
    except Exception as e:
        print(f"\n  [FATAL] 语法/导入测试阶段失败: {e}")
        traceback.print_exc()

    try:
        test_config_module(runner)
    except Exception as e:
        print(f"\n  [FATAL] 配置模块测试阶段失败: {e}")
        traceback.print_exc()

    try:
        test_scanner_module(runner)
    except Exception as e:
        print(f"\n  [FATAL] 扫描器模块测试阶段失败: {e}")
        traceback.print_exc()

    try:
        test_cleaner_module(runner)
    except Exception as e:
        print(f"\n  [FATAL] 清理器模块测试阶段失败: {e}")
        traceback.print_exc()

    try:
        test_utils_module(runner)
    except Exception as e:
        print(f"\n  [FATAL] 工具函数模块测试阶段失败: {e}")
        traceback.print_exc()

    try:
        test_gui_structure(runner)
    except Exception as e:
        print(f"\n  [FATAL] GUI 结构测试阶段失败: {e}")
        traceback.print_exc()

    try:
        test_end_to_end_safety(runner)
    except Exception as e:
        print(f"\n  [FATAL] 端到端安全测试阶段失败: {e}")
        traceback.print_exc()

    # 输出汇总报告
    results = runner.summary()

    # 输出失败测试详情
    failed = [r for r in results if not r.passed]
    if failed:
        print("\n失败测试详情:")
        for r in failed:
            print(f"  FAIL: {r.name} — {r.message}")

    return results


if __name__ == "__main__":
    main()
