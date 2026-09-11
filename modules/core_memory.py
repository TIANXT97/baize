"""CoreMemory - LLM-editable structured memory blocks."""
import sqlite3
import logging
from typing import Dict, Optional
from datetime import datetime

log = logging.getLogger("baize")

DEFAULT_BLOCKS = {
    "user_profile": "",
    "current_project": "",
    "key_decisions": "",
}

class CoreMemory:
    """Manage 3 structured memory blocks that can be edited by the agent."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_table()

    def _init_table(self):
        """Create core_memory table if not exists."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS core_memory (
                block_name TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT 'default',
                content TEXT NOT NULL DEFAULT '',
                updated_at TEXT DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (block_name, user_id)
            )
        """)
        # 幂等迁移：老库补 user_id 列
        cols = [row[1] for row in conn.execute("PRAGMA table_info(core_memory)").fetchall()]
        if "user_id" not in cols:
            conn.execute(
                "ALTER TABLE core_memory ADD COLUMN user_id TEXT NOT NULL DEFAULT 'default'"
            )
            log.info("Migration: added core_memory.user_id column")
        # Insert default blocks if not exist
        for block_name, default_content in DEFAULT_BLOCKS.items():
            conn.execute(
                "INSERT OR IGNORE INTO core_memory (block_name, user_id, content) VALUES (?, 'default', ?)",
                (block_name, default_content)
            )
        conn.commit()
        conn.close()

    def get_all(self, user_id: str = "default") -> Dict[str, str]:
        """Get all core memory blocks for a user."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT block_name, content, updated_at FROM core_memory WHERE user_id = ?",
            (user_id,),
        )
        result = {}
        for row in cur.fetchall():
            result[row["block_name"]] = {
                "content": row["content"],
                "updated_at": row["updated_at"],
            }
        conn.close()
        return result

    def get(self, block_name: str, user_id: str = "default") -> Optional[Dict]:
        """Get a single core memory block."""
        if block_name not in DEFAULT_BLOCKS:
            return None
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT block_name, content, updated_at FROM core_memory WHERE block_name = ? AND user_id = ?", (block_name, user_id))
        row = cur.fetchone()
        conn.close()
        if row:
            return {
                "block_name": row["block_name"],
                "content": row["content"],
                "updated_at": row["updated_at"],
            }
        return None

    def update(self, block_name: str, content: str, user_id: str = "default") -> bool:
        """Update a core memory block."""
        if block_name not in DEFAULT_BLOCKS:
            return False
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute(
            "INSERT OR REPLACE INTO core_memory (block_name, user_id, content, updated_at) "
            "VALUES (?, ?, ?, datetime('now','localtime'))",
            (block_name, user_id, content),
        )
        conn.commit()
        conn.close()
        log.info(f"CoreMemory block '{block_name}' updated for user '{user_id}' ({len(content)} chars)")
        return True

    def format_for_injection(self) -> str:
        """Format core memory blocks for system prompt injection."""
        blocks = self.get_all()
        parts = []
        for block_name, data in blocks.items():
            content = data.get("content", "").strip()
            if content:
                label = {
                    "user_profile": "User Profile",
                    "current_project": "Current Project",
                    "key_decisions": "Key Decisions",
                }.get(block_name, block_name)
                parts.append(f"[{label}]\n{content}")
        if parts:
            return "[CoreMemory]\n" + "\n\n".join(parts)
        return ""
