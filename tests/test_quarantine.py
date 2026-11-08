# -*- coding: utf-8 -*-
"""隔离恢复子系统无头单测（不需要 GUI / 真实系统文件）。

用临时目录模拟真实移动/恢复/清除，验证：
- 文件/目录隔离后可一键恢复（原始父目录自动重建）
- 同名去重
- 永久清除（单项 / 全部）
- 隔离副本丢失时列表自动过滤
"""
import os
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quarantine import Quarantine  # noqa: E402


class TestQuarantine(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="q_test_")
        self._base = os.path.join(self._tmp, "quarantine")
        self._src = os.path.join(self._tmp, "src")
        os.makedirs(self._src)
        self.q = Quarantine(base_dir=self._base)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_file(self, path, content=b"hello"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def test_move_and_restore_file(self):
        fp = self._make_file(os.path.join(self._src, "a.txt"))
        qid = self.q.move_to_quarantine(fp, category="测试")
        self.assertIsNotNone(qid)
        self.assertFalse(os.path.exists(fp))              # 原文件已移走
        self.assertEqual(len(self.q.list_items()), 1)
        ok = self.q.restore(qid)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(fp))              # 已恢复
        self.assertEqual(len(self.q.list_items()), 0)    # 清单清空

    def test_move_and_restore_dir(self):
        d = os.path.join(self._src, "cache")
        self._make_file(os.path.join(d, "x.bin"))
        self._make_file(os.path.join(d, "sub", "y.bin"))
        qid = self.q.move_to_quarantine(d, category="缓存")
        self.assertIsNotNone(qid)
        self.assertFalse(os.path.exists(d))
        ok = self.q.restore(qid)
        self.assertTrue(ok)
        self.assertTrue(os.path.isfile(os.path.join(d, "x.bin")))
        self.assertTrue(os.path.isfile(os.path.join(d, "sub", "y.bin")))

    def test_restore_rebuilds_parent(self):
        nested = os.path.join(self._src, "deep", "sub", "f.txt")
        self._make_file(nested)
        qid = self.q.move_to_quarantine(nested, category="测试")
        # 删掉原始父目录，验证恢复时自动重建
        shutil.rmtree(os.path.join(self._src, "deep"), ignore_errors=True)
        self.assertFalse(os.path.exists(os.path.join(self._src, "deep")))
        ok = self.q.restore(qid)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(nested))

    def test_dedup_same_basename(self):
        fp1 = self._make_file(os.path.join(self._src, "dup.txt"))
        fp2 = self._make_file(os.path.join(self._tmp, "other", "dup.txt"))
        q1 = self.q.move_to_quarantine(fp1, category="A")
        q2 = self.q.move_to_quarantine(fp2, category="B")
        self.assertIsNotNone(q1)
        self.assertIsNotNone(q2)
        names = [os.path.basename(r["quarantine_path"]) for r in self.q.list_items()]
        self.assertEqual(len(names), 2)
        self.assertIn("dup.txt", names)
        self.assertIn("dup_1.txt", names)

    def test_purge_single(self):
        fp = self._make_file(os.path.join(self._src, "g.txt"))
        qid = self.q.move_to_quarantine(fp, category="测试")
        ok = self.q.purge(qid)
        self.assertTrue(ok)
        self.assertEqual(len(self.q.list_items()), 0)
        # 隔离副本已不存在
        self.assertFalse(any(True for _ in os.listdir(self._base) if _.startswith("g")))

    def test_purge_all(self):
        self._make_file(os.path.join(self._src, "1.txt"))
        self._make_file(os.path.join(self._src, "2.txt"))
        self.q.move_to_quarantine(os.path.join(self._src, "1.txt"))
        self.q.move_to_quarantine(os.path.join(self._src, "2.txt"))
        n = self.q.purge_all()
        self.assertEqual(n, 2)
        self.assertEqual(self.q.count(), 0)

    def test_list_excludes_lost_copy(self):
        fp = self._make_file(os.path.join(self._src, "lost.txt"))
        qid = self.q.move_to_quarantine(fp, category="测试")
        # 手动删除隔离副本，模拟丢失
        rec = self.q.list_items()[0]
        shutil.rmtree(rec["quarantine_path"], ignore_errors=True) \
            if os.path.isdir(rec["quarantine_path"]) else os.remove(rec["quarantine_path"])
        self.assertEqual(len(self.q.list_items()), 0)
        # 恢复应安全失败
        self.assertFalse(self.q.restore(qid))


if __name__ == "__main__":
    unittest.main(verbosity=2)
