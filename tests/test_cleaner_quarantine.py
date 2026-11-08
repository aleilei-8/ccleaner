# -*- coding: utf-8 -*-
"""Cleaner 隔离集成测试（无头，用临时隔离区验证接线）。"""
import os
import sys
import shutil
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cleaner import Cleaner, CleanResult  # noqa: E402
from quarantine import Quarantine  # noqa: E402


def _cat(name, files, clean_target="files"):
    return SimpleNamespace(
        name=name, enabled=True, files=files, file_count=len(files),
        total_size=sum(os.path.getsize(f) for f in files if os.path.exists(f)),
        clean_target=clean_target,
    )


class TestCleanerQuarantine(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cln_q_")
        self._base = os.path.join(self._tmp, "quarantine")
        self._q = Quarantine(base_dir=self._base)
        self._cleaner = Cleaner(quarantine=self._q)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_files_quarantined_not_deleted(self):
        f1 = os.path.join(self._tmp, "x.tmp")
        f2 = os.path.join(self._tmp, "y.tmp")
        for p in (f1, f2):
            with open(p, "w") as fh:
                fh.write("data")
        cats = {"临时文件": _cat("临时文件", [f1, f2], "files")}
        res = self._cleaner.clean_categories(cats, dry_run=False, use_quarantine=True)
        self.assertEqual(res.files_deleted, 0)
        self.assertEqual(res.files_quarantined, 2)
        self.assertEqual(len(res.quarantine_ids), 2)
        self.assertFalse(os.path.exists(f1))
        self.assertFalse(os.path.exists(f2))
        self.assertEqual(len(self._q.list_items()), 2)

    def test_quarantine_off_permanent_delete(self):
        f1 = os.path.join(self._tmp, "z.tmp")
        with open(f1, "w") as fh:
            fh.write("data")
        cats = {"临时文件": _cat("临时文件", [f1], "files")}
        res = self._cleaner.clean_categories(cats, dry_run=False, use_quarantine=False)
        self.assertEqual(res.files_deleted, 1)
        self.assertEqual(res.files_quarantined, 0)
        self.assertFalse(os.path.exists(f1))

    def test_dir_quarantined(self):
        d = os.path.join(self._tmp, "cachedir")
        os.makedirs(os.path.join(d, "a"))
        with open(os.path.join(d, "a", "b.bin"), "w") as fh:
            fh.write("x")
        cats = {"缓存": _cat("缓存", [d], "dir")}
        res = self._cleaner.clean_categories(cats, dry_run=False, use_quarantine=True)
        self.assertEqual(res.files_quarantined, 1)
        self.assertFalse(os.path.exists(d))
        self.assertEqual(len(self._q.list_items()), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
