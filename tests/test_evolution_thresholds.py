import os
import sqlite3
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from modules.evolution import EvolutionTracker, RELATION_THRESHOLDS  # noqa: E402

OLD_TEXT = "用户喜欢蓝色篮球游泳"
NEW_TEXT = "用户喜欢蓝色咖啡跑步"


class TestEvolutionThresholds(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(prefix="baize_evo_"), "facts.db")
        conn = sqlite3.connect(self.db)
        conn.execute("""CREATE TABLE memories (
            id INTEGER PRIMARY KEY, user_id TEXT, content TEXT,
            confirm_count INTEGER NOT NULL DEFAULT 0)""")
        conn.execute("""CREATE TABLE knowledge_evolution (
            id INTEGER PRIMARY KEY AUTOINCREMENT, source_id INTEGER, target_id INTEGER,
            relation TEXT, confidence REAL, reason TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')))""")
        conn.execute("INSERT INTO memories (id, user_id, content) VALUES (1, 'default', ?)", (OLD_TEXT,))
        conn.execute("INSERT INTO memories (id, user_id, content) VALUES (2, 'default', ?)", (NEW_TEXT,))
        conn.commit()
        conn.close()
        self.tracker = EvolutionTracker(self.db)

    def test_confirms_threshold_below_gate(self):
        self.assertLess(RELATION_THRESHOLDS["confirms"], 0.6)

    def test_jaccard_04_confirms_passes_gate_in_check_evolution(self):
        rels = self.tracker.check_evolution(NEW_TEXT, new_id=2, user_id="default")
        confirms = [r for r in rels if r["relation"] == "confirms" and r["target_id"] == 1]
        self.assertEqual(len(confirms), 1)
        self.assertLess(confirms[0]["confidence"], 0.6)


if __name__ == "__main__":
    unittest.main()
