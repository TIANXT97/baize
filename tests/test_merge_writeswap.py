import importlib.util
import os
import sqlite3
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from modules.auto_dream import AutoDream  # noqa: E402


def _make_db(path):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL DEFAULT 'default',
            category TEXT NOT NULL DEFAULT 'general',
            content TEXT NOT NULL,
            lane TEXT DEFAULT 'general',
            importance REAL DEFAULT 0.5,
            access_count INTEGER DEFAULT 0,
            last_accessed TEXT,
            source TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            expires_at TEXT,
            origin TEXT DEFAULT 'unknown',
            confirm_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE memory_states (
            memory_id INTEGER PRIMARY KEY,
            state TEXT DEFAULT 'active',
            reason TEXT,
            source TEXT,
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        INSERT INTO memories (id, user_id, content, lane, created_at) VALUES
            (1, 'default', 'fact one', 'general', datetime('now','localtime')),
            (2, 'default', 'fact two', 'general', datetime('now','localtime'));
    """)
    conn.commit()
    conn.close()


def _active_ids(path):
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute("SELECT id FROM memories WHERE id NOT IN "
                            "(SELECT memory_id FROM memory_states WHERE state='superseded')").fetchall()
        return sorted(r[0] for r in rows)
    finally:
        conn.close()


class TestMergeWriteThenSwap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="baize_merge_")
        self.db = os.path.join(self.tmp, "facts.db")
        _make_db(self.db)

    def _dream(self, llm_result, update_ok=True):
        ad = AutoDream(self.db, api_url="http://x", api_key="k", model="m")
        ad._call_llm = lambda prompt: llm_result
        if not update_ok:
            ad._update_content = lambda *a, **k: False
        return ad.run_distillation(days=7, user_id="default")

    def test_empty_merged_content_keeps_sources_active(self):
        self._dream({"distilled": [{"keep_id": 1, "merge_ids": [2], "merged_content": ""}]})
        self.assertEqual(_active_ids(self.db), [1, 2])

    def test_update_failure_keeps_sources_active(self):
        self._dream({"distilled": [{"keep_id": 1, "merge_ids": [2], "merged_content": "merged"}]},
                    update_ok=False)
        self.assertEqual(_active_ids(self.db), [1, 2])

    def test_successful_merge_supersedes_sources(self):
        self._dream({"distilled": [{"keep_id": 1, "merge_ids": [2], "merged_content": "merged"}]})
        self.assertEqual(_active_ids(self.db), [1])

    def test_keep_id_in_merge_ids_is_not_superseded(self):
        self._dream({"distilled": [{"keep_id": 1, "merge_ids": [1, 2], "merged_content": "merged"}]})
        self.assertEqual(_active_ids(self.db), [1])


if __name__ == "__main__":
    unittest.main()
