# -*- coding: utf-8 -*-
"""隔离恢复子系统 v4.0

核心安全升级：清理不再"永久删除"，默认把文件/目录「移动」到隔离区(quarantine)，
并记录原始路径清单(manifest)，支持一键恢复(撤销)。彻底杜绝误删不可逆。

设计要点（贴合"绝不误删、支持一键撤销"安全哲学）：
- 隔离区位于 %LOCALAPPDATA%/CCleaner/quarantine（与真实删除解耦）
- 每个被隔离项生成唯一 id，manifest 记录 original_path / size / time / category / type
- move_fn / remove_fn 可注入，便于无头单测（不动真实系统文件）
- 同名冲突自动加 _1/_2 后缀，避免覆盖历史隔离项
- 恢复时自动重建原始父目录；永久清除(purge)才真正删除隔离区里的副本
"""
import os
import sys
import json
import time
import shutil
import logging
import threading
import uuid
from typing import Dict, List, Optional, Callable

logger = logging.getLogger(__name__)


def default_base_dir() -> str:
    """隔离区默认根目录：%LOCALAPPDATA%/CCleaner/quarantine。"""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "CCleaner", "quarantine")


class Quarantine:
    """隔离区管理器。

    move_fn / remove_fn 可注入（默认 shutil.move / 真实删除），便于测试。
    """

    def __init__(self, base_dir: Optional[str] = None,
                 move_fn: Optional[Callable[[str, str], None]] = None,
                 remove_fn: Optional[Callable[[str], None]] = None):
        self.base = base_dir or default_base_dir()
        self._move_fn = move_fn or self._real_move
        self._remove_fn = remove_fn or self._real_remove
        self._manifest_path = os.path.join(self.base, "manifest.json")
        self._lock = threading.RLock()
        self.ensure()

    # ======================== 基础设施 ========================

    def ensure(self) -> None:
        """确保隔离区目录存在（异常吸收，不阻断主流程）。"""
        try:
            os.makedirs(self.base, exist_ok=True)
        except Exception as e:
            logger.warning("隔离区目录创建失败 %s: %s", self.base, e)

    def _real_move(self, src: str, dst: str) -> None:
        shutil.move(src, dst)

    def _real_remove(self, path: str) -> None:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.remove(path)
            except OSError:
                shutil.rmtree(path, ignore_errors=True)

    def _load_manifest(self) -> List[Dict]:
        if not os.path.exists(self._manifest_path):
            return []
        try:
            with open(self._manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning("隔离清单读取失败: %s", e)
            return []

    def _save_manifest(self, records: List[Dict]) -> None:
        try:
            tmp = self._manifest_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self._manifest_path)
        except Exception as e:
            logger.warning("隔离清单写入失败: %s", e)

    @staticmethod
    def _dedup_name(target_dir: str, name: str) -> str:
        """在 target_dir 内避免重名：存在则追加 _1/_2。"""
        cand = os.path.join(target_dir, name)
        if not os.path.exists(cand):
            return cand
        stem, ext = os.path.splitext(name)
        i = 1
        while True:
            cand = os.path.join(target_dir, f"{stem}_{i}{ext}")
            if not os.path.exists(cand):
                return cand
            i += 1

    # ======================== 隔离 ========================

    def move_to_quarantine(self, src_path: str, original_root: str = "",
                           category: str = "") -> Optional[str]:
        """把 src_path 移入隔离区，返回隔离 id；失败返回 None。

        Args:
            src_path: 要隔离的文件或目录（必须是真实存在的路径）。
            original_root: 类别根目录（仅用于记录/展示，不参与恢复路径）。
            category: 类别名（用于展示）。
        """
        if not os.path.exists(src_path):
            return None
        with self._lock:
            self.ensure()
            try:
                size = self._path_size(src_path)
            except OSError:
                size = 0
            name = os.path.basename(src_path) or "_root_"
            dst = self._dedup_name(self.base, name)
            try:
                self._move_fn(src_path, dst)
            except Exception as e:
                logger.error("隔离失败 %s: %s", src_path, e)
                return None
            qid = uuid.uuid4().hex[:12]
            rec = {
                "id": qid,
                "original_path": os.path.abspath(src_path),
                "quarantine_path": os.path.abspath(dst),
                "size": size,
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "category": category,
                "type": "dir" if os.path.isdir(dst) else "file",
            }
            records = self._load_manifest()
            records.append(rec)
            self._save_manifest(records)
            logger.info("已隔离: %s -> %s (id=%s)", src_path, dst, qid)
            return qid

    @staticmethod
    def _path_size(path: str) -> int:
        if os.path.isfile(path):
            try:
                return os.path.getsize(path)
            except OSError:
                return 0
        total = 0
        try:
            for root, _, files in os.walk(path):
                for fn in files:
                    fp = os.path.join(root, fn)
                    try:
                        total += os.path.getsize(fp)
                    except OSError:
                        pass
        except OSError:
            pass
        return total

    # ======================== 恢复 / 清除 ========================

    def restore(self, qid: str) -> bool:
        """把隔离项恢复回原始路径。成功返回 True。"""
        with self._lock:
            records = self._load_manifest()
            rec = next((r for r in records if r.get("id") == qid), None)
            if not rec:
                logger.warning("恢复失败：隔离项不存在 %s", qid)
                return False
            src = rec["quarantine_path"]
            dst = rec["original_path"]
            if not os.path.exists(src):
                logger.warning("恢复失败：隔离副本已丢失 %s", src)
                self._save_manifest([r for r in records if r["id"] != qid])
                return False
            try:
                parent = os.path.dirname(dst)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                # 若原始位置已有同名真实文件，先不覆盖（保护现场）
                if os.path.exists(dst):
                    dst = self._dedup_name(os.path.dirname(dst), os.path.basename(dst))
                self._move_fn(src, dst)
            except Exception as e:
                logger.error("恢复失败 %s -> %s: %s", src, dst, e)
                return False
            self._save_manifest([r for r in records if r["id"] != qid])
            logger.info("已恢复: %s -> %s", qid, dst)
            return True

    def purge(self, qid: str) -> bool:
        """永久删除隔离区里的某一项副本（不可恢复）。"""
        with self._lock:
            records = self._load_manifest()
            rec = next((r for r in records if r.get("id") == qid), None)
            if not rec:
                return False
            try:
                self._remove_fn(rec["quarantine_path"])
            except Exception as e:
                logger.warning("永久清除失败 %s: %s", rec["quarantine_path"], e)
            self._save_manifest([r for r in records if r["id"] != qid])
            return True

    def purge_all(self) -> int:
        """永久清空整个隔离区，返回清除项数。"""
        with self._lock:
            records = self._load_manifest()
            n = 0
            for rec in records:
                try:
                    self._remove_fn(rec["quarantine_path"])
                    n += 1
                except Exception as e:
                    logger.warning("清除失败 %s: %s", rec["quarantine_path"], e)
            self._save_manifest([])
            return n

    # ======================== 查询 ========================

    def list_items(self) -> List[Dict]:
        """列出所有隔离项（按时间倒序）。"""
        with self._lock:
            recs = self._load_manifest()
            # 过滤掉隔离副本已丢失的项
            alive = [r for r in recs if os.path.exists(r.get("quarantine_path", ""))]
            return list(reversed(alive))

    def count(self) -> int:
        return len(self.list_items())
