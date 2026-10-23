import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from modules.hybrid_recall import (  # noqa: E402
    FTS_PHRASE_MIN_HITS,
    RECENT_POOL_IMPORTANCE_SLOTS,
    RECENT_POOL_LATEST_SLOTS,
    HybridRecall,
)


def _make_db(path):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY, user_id TEXT NOT NULL DEFAULT 'default', category TEXT,
            content TEXT NOT NULL, lane TEXT, importance REAL DEFAULT 0.5,
            access_count INTEGER DEFAULT 0, last_accessed TEXT, source TEXT,
            created_at TEXT, expires_at TEXT, origin TEXT DEFAULT 'unknown',
            confirm_count INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE memory_states (memory_id INTEGER PRIMARY KEY, state TEXT, reason TEXT, source TEXT, updated_at TEXT);
        CREATE VIRTUAL TABLE memories_fts USING fts5(
            content, category, source, content='memories', content_rowid='id', tokenize='trigram');
        CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
            INSERT INTO memories_fts(rowid, content, category, source)
            VALUES (new.id, new.content, new.category, new.source);
        END;
    """)
    conn.commit()
    conn.close()


def _insert(path, mem_id, content, importance=0.5, created_at=None):
    created_at = created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO memories (id, user_id, category, content, lane, importance, source, created_at) "
        "VALUES (?, 'default', 'general', ?, 'general', ?, 'test', ?)",
        (mem_id, content, importance, created_at),
    )
    conn.commit()
    conn.close()


class _StubEvolution:
    def get_related(self, *a, **k):
        return {}

    def is_superseded_batch(self, ids):
        return set()


class TestFtsPhraseFallback(unittest.TestCase):
    QUERY = "canary recall voyage deepseek"

    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(prefix="baize_fts_"), "facts.db")
        _make_db(self.db)
        self.hr = HybridRecall(db_path=self.db, embed_key_path="", evolution=None)

    def _ids(self):
        return {r["id"] for r in self.hr._fts_search(self.QUERY, "default", 25)}

    def test_single_phrase_hit_does_not_block_keyword_fallback(self):
        _insert(self.db, 1, f"设计文档：巡检问句 {self.QUERY} 的判定规则")
        _insert(self.db, 2, "决议：deepseek 提取正常，voyage 向量落盘，canary recall 通过", 0.8)
        self.assertEqual(self._ids(), {1, 2})

    def test_enough_phrase_hits_keep_phrase_only(self):
        for i in range(1, FTS_PHRASE_MIN_HITS + 1):
            _insert(self.db, i, f"规则{i}：{self.QUERY} 必须通过")
        keyword_only_id = FTS_PHRASE_MIN_HITS + 1
        _insert(self.db, keyword_only_id, "deepseek 与 voyage 都正常，canary 与 recall 无关联")
        ids = self._ids()
        self.assertEqual(ids, set(range(1, FTS_PHRASE_MIN_HITS + 1)))
        self.assertNotIn(keyword_only_id, ids)

    def test_zero_phrase_hits_still_fall_back_to_keywords(self):
        _insert(self.db, 1, "deepseek 提取正常，voyage 向量落盘")
        self.assertEqual(self._ids(), {1})


class TestRecentPoolQuota(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(prefix="baize_pool_"), "facts.db")
        _make_db(self.db)
        self.hr = HybridRecall(db_path=self.db, embed_key_path="", evolution=_StubEvolution())
        self.hr._fts_search = lambda *a, **k: []
        self.hr._vector_search = lambda *a, **k: []
        self.hr._seat_scores = lambda query, ids: {i: 0.5 for i in ids}

    def _search(self):
        return self.hr.search("任意问句", "default", limit=200, return_trace=True)

    def test_new_lower_importance_memories_keep_a_seat(self):
        base = datetime.now() - timedelta(hours=2)
        high_total = RECENT_POOL_IMPORTANCE_SLOTS + RECENT_POOL_LATEST_SLOTS + 40
        for i in range(1, high_total + 1):
            _insert(self.db, i, f"核心业务记忆 {i}", 0.9, (base + timedelta(seconds=i)).strftime("%Y-%m-%d %H:%M:%S"))
        newest_ids = list(range(high_total + 1, high_total + 4))
        for i in newest_ids:
            _insert(self.db, i, f"金丝雀新记忆 {i}", 0.8)

        out = self._search()
        pooled = {r["id"] for r in out["results"] if r["source"] == "recent_pool"}
        self.assertTrue(set(newest_ids) <= pooled)
        self.assertEqual(out["trace"]["stages"]["recent_pool_added"], RECENT_POOL_IMPORTANCE_SLOTS + RECENT_POOL_LATEST_SLOTS)

    def test_small_pool_has_no_duplicates(self):
        for i in range(1, 6):
            _insert(self.db, i, f"近期记忆 {i}", 0.5 + i / 20)
        out = self._search()
        self.assertEqual(out["trace"]["stages"]["recent_pool_added"], 5)
        ids = [r["id"] for r in out["results"]]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
