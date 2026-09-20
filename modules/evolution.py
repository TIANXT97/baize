"""Knowledge Evolution Tracker - detect relationships between new and existing memories."""
import re
import hashlib
import sqlite3
import logging
from typing import List, Dict, Optional, Tuple

log = logging.getLogger("baize")

# 极性翻转关键词
POLARITY_FLIP = re.compile(r'不再|改为|改成|取代|换成|以前|之前|现在不|已经不|不(再|是|喜欢|想要)')


def _chunked(seq, size):
    """分批序列（SQLite IN 子句避免变量数上限，B1）。"""
    for i in range(0, len(seq), size):
        yield seq[i:i + size]

class EvolutionTracker:
    """Track knowledge evolution between memories."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_tables()

    def _init_tables(self):
        """Create evolution tables if not exist."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS memory_states (
                memory_id INTEGER PRIMARY KEY,
                state TEXT DEFAULT 'active',
                reason TEXT,
                source TEXT,
                updated_at TEXT DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS knowledge_evolution (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER,
                target_id INTEGER,
                relation TEXT,
                confidence REAL,
                reason TEXT,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );
        """)
        conn.close()

    def check_evolution(self, new_fact: str, new_id: int, user_id: str = "default") -> List[Dict]:
        """Check new fact against existing memories for evolution relationships.

        D3: _find_similar 按 user_id 过滤候选；写入前再次校验关系两端归属。
        """
        # Get top-5 similar memories by Jaccard (exclude self)
        candidates = self._find_similar(new_fact, limit=5, exclude_id=new_id, user_id=user_id)
        relationships = []

        for cand in candidates:
            relation, confidence, reason = self._classify_relation(new_fact, cand["content"])
            if relation and confidence >= 0.6:
                relationships.append({
                    "source_id": new_id,
                    "target_id": cand["id"],
                    "relation": relation,
                    "confidence": confidence,
                    "reason": reason,
                })
                # If replaces, mark old memory as superseded
                if relation == "replaces":
                    self._mark_superseded(cand["id"], reason, new_id, user_id)

        # Log relationships
        for rel in relationships:
            self._log_evolution(rel, user_id)

        return relationships

    def _find_similar(self, text: str, limit: int = 5, exclude_id: int = None,
                      user_id: str = "default") -> List[Dict]:
        """Find similar memories by content similarity.

        D3: 按 user_id 过滤，避免跨用户候选。
        """
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        # Get recent memories and compute Jaccard (exclude self)
        cur.execute(
            "SELECT id, content FROM memories WHERE user_id = ? ORDER BY id DESC LIMIT 500",
            (user_id,)
        )
        candidates = []
        for row in cur.fetchall():
            if row["id"] == exclude_id:
                continue
            sim = self._jaccard(text, row["content"])
            if sim > 0.15:
                candidates.append({"id": row["id"], "content": row["content"], "similarity": sim})
        conn.close()
        candidates.sort(key=lambda x: x["similarity"], reverse=True)
        return candidates[:limit]

    def _get_bigrams(self, text: str) -> set:
        """Extract token set from text: Chinese char bigrams + single chars + English words.

        Shared by _jaccard and _classify_relation to avoid duplicate definitions.
        """
        chars = re.findall(r'[\u4e00-\u9fff]', text)
        eng_words = re.findall(r'[a-zA-Z]+', text)
        bigrams = set()
        # Chinese char bigrams
        for i in range(len(chars) - 1):
            bigrams.add(chars[i] + chars[i+1])
        # Single chars (helps short texts)
        for c in chars:
            bigrams.add(c)
        # English words (lowercased)
        for w in eng_words:
            bigrams.add(w.lower())
        return bigrams

    def _jaccard(self, text1: str, text2: str) -> float:
        """Compute Jaccard similarity between two texts using character bigrams."""
        words1 = self._get_bigrams(text1)
        words2 = self._get_bigrams(text2)
        if not words1 or not words2:
            return 0.0
        intersection = words1 & words2
        union = words1 | words2
        return len(intersection) / len(union)

    def _classify_relation(self, new_text: str, old_text: str) -> Tuple[Optional[str], float, str]:
        """Classify relationship between new and old memory.

        Reform: 彻底废除 Jaccard 线性乘积作为取代置信度的错误公式。
        长句纠错时词汇并集大导致 Jaccard 极低（实测 0.23），
        导致置信度被锁死在 0.27（<0.6），永远无法触发 replaces。
        新规则：极性翻转 + 共同词>=3 → 直接判定 replaces, confidence=0.85。
        """
        jaccard = self._jaccard(new_text, old_text)

        # Check polarity flip
        has_flip = bool(POLARITY_FLIP.search(new_text))

        # Check common topics using shared bigram extractor
        new_words = self._get_bigrams(new_text)
        old_words = self._get_bigrams(old_text)
        common_topics = new_words & old_words

        if has_flip and len(common_topics) >= 3:
            # Reform: 极性翻转+共同话题充分 → 直接判定 replaces，置信度 0.85
            return "replaces", 0.85, f"极性翻转+共同话题{len(common_topics)}个"
        elif jaccard > 0.5 and not has_flip:
            # enriches: high direct similarity
            confidence = min(0.95, jaccard)
            return "enriches", round(confidence, 2), f"高相似度{jaccard:.2f}"
        elif jaccard > 0.3 and not has_flip:
            # confirms: moderate similarity, slightly conservative
            confidence = min(0.90, jaccard * 0.95)
            return "confirms", round(confidence, 2), f"中相似度{jaccard:.2f}"
        elif has_flip and len(common_topics) >= 2:
            # challenges: flip present but weak evidence
            confidence = min(0.85, jaccard * 0.85)
            return "challenges", round(confidence, 2), "极性翻转但话题少"
        return None, 0.0, ""

    def _mark_superseded(self, memory_id: int, reason: str, source_id: int,
                         user_id: str = "default"):
        """Mark a memory as superseded.

        D3: 先确认目标记忆存在且属于 user_id，避免跨用户影响。
        Reform: 同步将旧记忆内容写入 rejected_values 墓碑表。
        """
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        try:
            cur = conn.cursor()
            cur.execute("SELECT user_id, content FROM memories WHERE id = ?", (memory_id,))
            row = cur.fetchone()
            if not row:
                log.warning(f"Evolution: skip supersede memory {memory_id}: not found")
                return False
            if row[0] != user_id:
                log.warning(
                    f"Evolution: skip supersede memory {memory_id}: "
                    f"belongs to user '{row[0]}', not '{user_id}'"
                )
                return False
            old_content = row[1]
            cur.execute("""
                INSERT OR REPLACE INTO memory_states (memory_id, state, reason, source, updated_at)
                VALUES (?, 'superseded', ?, ?, datetime('now','localtime'))
            """, (memory_id, reason, str(source_id)))
            # Reform: 写墓碑表，阻断已否决事实换 ID 复活
            norm_text = re.sub(r'[\s\W]+', '', old_content).lower()
            content_hash = hashlib.sha256(norm_text.encode('utf-8')).hexdigest()
            cur.execute(
                "INSERT OR IGNORE INTO rejected_values (content_hash, content_pattern, reason, rejected_by_id) VALUES (?, ?, ?, ?)",
                (content_hash, old_content[:100], reason, source_id)
            )
            conn.commit()
            log.info(f"Memory {memory_id} marked superseded by {source_id}: {reason}")
            return True
        finally:
            conn.close()

    def _log_evolution(self, rel: Dict, user_id: str = "default"):
        """Log evolution relationship.

        D3: knowledge_evolution 无 user_id 列，写入前反查两端归属，否则丢弃。
        """
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        try:
            cur = conn.cursor()
            if not self._both_owned(conn, rel["source_id"], rel["target_id"], user_id):
                log.warning(
                    f"Evolution: skip relation {rel['relation']} "
                    f"({rel['source_id']}->{rel['target_id']}): "
                    f"not all ids owned by user '{user_id}'"
                )
                return
            cur.execute("""
                INSERT INTO knowledge_evolution (source_id, target_id, relation, confidence, reason)
                VALUES (?, ?, ?, ?, ?)
            """, (rel["source_id"], rel["target_id"], rel["relation"], rel["confidence"], rel["reason"]))
            # P2b: confirms 关系累积目标记忆的置信度（偏好/身份记忆越被确认越权威）
            # 归属已由 _both_owned 校验，UPDATE 仍带 user_id 兜底防跨用户
            if rel["relation"] == "confirms":
                cur.execute(
                    "UPDATE memories SET confirm_count = confirm_count + 1 "
                    "WHERE id = ? AND user_id = ?",
                    (rel["target_id"], user_id),
                )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _both_owned(conn, source_id: int, target_id: int, user_id: str) -> bool:
        """校验 source/target 两条记忆均属于 user_id（D3）。"""
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM memories WHERE id IN (?, ?) AND user_id = ?",
            (source_id, target_id, user_id),
        )
        return cur.fetchone()[0] == 2

    def is_superseded(self, memory_id: int) -> bool:
        """Check if a memory is superseded."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        cur = conn.cursor()
        cur.execute("SELECT state FROM memory_states WHERE memory_id = ?", (memory_id,))
        row = cur.fetchone()
        conn.close()
        return row and row[0] == "superseded"

    def is_superseded_batch(self, memory_ids) -> set:
        """B1: 批量判断哪些记忆已 superseded，返回 superseded 的 id 集合。

        一次 IN 查询取回全部，替代逐条 is_superseded（每条一次 SQLite 连接）。
        图谱扩展每跳、检索末尾过滤各用一次，连接数从 O(节点数) 降到 O(调用数)。
        """
        if not memory_ids:
            return set()
        ids = list(dict.fromkeys(memory_ids))
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        try:
            cur = conn.cursor()
            superseded = set()
            for chunk in _chunked(ids, 200):
                ph = ",".join("?" * len(chunk))
                cur.execute(
                    f"SELECT memory_id FROM memory_states "
                    f"WHERE memory_id IN ({ph}) AND state = 'superseded'",
                    list(chunk),
                )
                superseded.update(row[0] for row in cur.fetchall())
            return superseded
        finally:
            conn.close()

    def get_related(self, memory_ids, hops: int = 2, max_per_hop: int = 8,
                    user_id: Optional[str] = None) -> Dict[int, Dict]:
        """P1-2: 沿 knowledge_evolution 关系边做多跳扩展，返回关联记忆。

        Args:
            memory_ids: 种子记忆 ID 列表（检索命中项）
            hops: 扩展跳数（1-2）
            max_per_hop: 每跳最多扩展出的节点数

        Returns:
            {related_id: {"relation": str, "confidence": float, "hop": int}}
            排除种子自身与 superseded 记忆。

        B1: superseded 判断改为 hop 级批量（is_superseded_batch），不再逐邻居
            单查，连接数从 O(候选节点数) 降到 O(跳数)。
        B2: 去掉 SQL LIMIT —— hub 节点大量低分边不再把 `max_per_hop*3` 的窗口
            吃光、饿死其它分支；改为取回 frontier 全部出/入边后在 Python 侧按
            max_per_hop 截断。hop>=2 的节点 confidence 沿路径连乘前序边
            confidence（种子前序为 1.0），不再只取最后一条边的值。
            conn 用 try/finally 保证异常时也关闭。
        D3: user_id 非空时，每跳对候选邻居做归属过滤（knowledge_evolution
            无 user_id 列，需反查 memories），只扩展该用户的记忆。
        """
        if not memory_ids or not hops:
            return {}
        frontier = set(memory_ids)
        seen = set(memory_ids)
        related: Dict[int, Dict] = {}
        # 节点到达时的路径置信度：种子=1.0，hop N = 前序边 confidence 连乘
        conf_map: Dict[int, float] = {mid: 1.0 for mid in frontier}

        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            for hop in range(1, hops + 1):
                if not frontier:
                    break
                # B2: 分批取 frontier 的全部出/入边（无 SQL LIMIT，截断在 Python 侧）
                rows = []
                for chunk in _chunked(list(frontier), 200):
                    ph = ",".join("?" * len(chunk))
                    rows.extend(cur.execute(
                        f"""SELECT source_id, target_id, relation, confidence
                            FROM knowledge_evolution
                            WHERE source_id IN ({ph}) OR target_id IN ({ph})""",
                        list(chunk) + list(chunk),
                    ).fetchall())

                # 汇总本 hop 候选：同一节点多条到达路径时保留路径置信度最高者
                best: Dict[int, Tuple[float, str]] = {}
                for row in rows:
                    src, tgt = row["source_id"], row["target_id"]
                    # 取对端（非 frontier 侧）
                    neighbor = tgt if src in frontier else src
                    if neighbor in seen:
                        continue
                    # B2: 路径置信度连乘前序边（hop=1 前序为种子 1.0）
                    path_conf = row["confidence"] * conf_map.get(src, 1.0)
                    if neighbor not in best or path_conf > best[neighbor][0]:
                        best[neighbor] = (path_conf, row["relation"])

                # D3: 只保留属于该用户的候选邻居（反查 memories）
                if user_id is not None and best:
                    owned = set()
                    for chunk in _chunked(list(best.keys()), 200):
                        ph = ",".join("?" * len(chunk))
                        owned.update(r[0] for r in cur.execute(
                            f"SELECT id FROM memories WHERE id IN ({ph}) AND user_id = ?",
                            list(chunk) + [user_id],
                        ).fetchall())
                    best = {n: v for n, v in best.items() if n in owned}

                if not best:
                    frontier = set()
                    break

                # B1: hop 级批量 superseded 判断（一次 IN 查询）
                superseded = self.is_superseded_batch(list(best.keys()))

                # B2: 按路径置信度降序，Python 侧截断到 max_per_hop
                next_frontier = set()
                added = 0
                for neighbor, (path_conf, relation) in sorted(
                        best.items(), key=lambda kv: kv[1][0], reverse=True):
                    # 全部候选记入 seen，避免后续 hop 再次候选/扩展
                    seen.add(neighbor)
                    if neighbor in superseded:
                        continue
                    related[neighbor] = {
                        "relation": relation,
                        "confidence": path_conf,
                        "hop": hop,
                    }
                    conf_map[neighbor] = path_conf
                    next_frontier.add(neighbor)
                    added += 1
                    if added >= max_per_hop:
                        break
                frontier = next_frontier
        finally:
            conn.close()
        return related
