import importlib
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REQUIRED_TABLES = ["memories", "memory_states", "knowledge_evolution", "merge_suggestions"]
REQUIRED_INDEXES = [
    "idx_memory_states_state_mem",
    "idx_knowledge_evo_src",
    "idx_knowledge_evo_tgt",
    "idx_merge_sugg_keep",
]


class TestCleanStartup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="baize_clean_")
        for name in ("api_server.py", "config.json"):
            shutil.copy(os.path.join(PROJECT_ROOT, name), os.path.join(self.tmp, name))
        shutil.copytree(os.path.join(PROJECT_ROOT, "modules"), os.path.join(self.tmp, "modules"))
        self.sys_path_before = list(sys.path)
        sys.path.insert(0, self.tmp)

    def tearDown(self):
        sys.path[:] = self.sys_path_before
        for mod in [m for m in sys.modules if m == "api_server" or m.startswith("modules")]:
            del sys.modules[mod]
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fresh_empty_dir_startup_creates_all_tables_and_indexes(self):
        api_server = importlib.import_module("api_server")
        self.assertTrue(api_server.DB_PATH.startswith(self.tmp))

        conn = sqlite3.connect(api_server.DB_PATH)
        try:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        finally:
            conn.close()

        for t in REQUIRED_TABLES:
            self.assertIn(t, tables)
        for i in REQUIRED_INDEXES:
            self.assertIn(i, indexes)


if __name__ == "__main__":
    unittest.main()
