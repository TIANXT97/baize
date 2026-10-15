import os
import sqlite3
import sys
import tempfile
import unittest

import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from modules.hybrid_recall import HybridRecall  # noqa: E402


def _legacy_db(path):
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE memories (
        id INTEGER PRIMARY KEY, user_id TEXT NOT NULL DEFAULT 'default', category TEXT,
        content TEXT NOT NULL, lane TEXT, importance REAL DEFAULT 0.5,
        access_count INTEGER DEFAULT 0, last_accessed TEXT, source TEXT,
        created_at TEXT, expires_at TEXT, origin TEXT DEFAULT 'unknown',
        confirm_count INTEGER NOT NULL DEFAULT 0)""")
    conn.execute("CREATE TABLE memory_states (memory_id INTEGER PRIMARY KEY, state TEXT, reason TEXT, source TEXT, updated_at TEXT)")
    conn.execute("CREATE TABLE memory_vec_i8 (mem_id INTEGER PRIMARY KEY, vec BLOB NOT NULL)")
    conn.commit()
    conn.close()


def _blob(seed):
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(1024).astype(np.float32)
    v = v / np.linalg.norm(v)
    return np.clip(np.round(v * 127), -127, 127).astype(np.int8).tobytes()


class TestModelSpaceIsolation(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(prefix="baize_space_"), "facts.db")

    def test_legacy_schema_upgrade_defaults_to_voyage(self):
        _legacy_db(self.db)
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO memories (id, user_id, content) VALUES (1, 'default', 'legacy')")
        conn.execute("INSERT INTO memory_vec_i8 (mem_id, vec) VALUES (1, ?)", (_blob(1),))
        conn.commit()
        conn.close()

        HybridRecall(db_path=self.db, embed_key_path="", evolution=None)

        conn = sqlite3.connect(self.db)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(memory_vec_i8)").fetchall()]
        spaces = [r[0] for r in conn.execute("SELECT model_space FROM memory_vec_i8").fetchall()]
        conn.close()
        self.assertIn("model_space", cols)
        self.assertEqual(spaces, ["voyage-4-lite"])

    def test_search_only_returns_same_model_space(self):
        _legacy_db(self.db)
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO memories (id, user_id, content, category, lane, created_at) "
                     "VALUES (1, 'default', 'voyage row', 'general', 'general', '2026-10-15 10:00:00')")
        conn.execute("INSERT INTO memories (id, user_id, content, category, lane, created_at) "
                     "VALUES (2, 'default', 'bge row', 'general', 'general', '2026-10-15 10:00:00')")
        conn.execute("ALTER TABLE memory_vec_i8 ADD COLUMN model_space TEXT NOT NULL DEFAULT 'voyage-4-lite'")
        conn.execute("INSERT INTO memory_vec_i8 (mem_id, vec, model_space) VALUES (1, ?, 'voyage-4-lite')", (_blob(1),))
        conn.execute("INSERT INTO memory_vec_i8 (mem_id, vec, model_space) VALUES (2, ?, 'BAAI/bge-m3')", (_blob(2),))
        conn.commit()
        conn.close()

        hr = HybridRecall(db_path=self.db, embed_key_path="", evolution=None)
        hr.last_embed_model = "BAAI/bge-m3"
        hr._get_embedding = lambda *a, **k: list(np.random.default_rng(2).standard_normal(1024))
        hr.last_embed_model = "BAAI/bge-m3"
        results = hr._vector_search_i8("q", "default", limit=10)
        ids = [r["id"] for r in results]
        self.assertEqual(ids, [2])


if __name__ == "__main__":
    unittest.main()
