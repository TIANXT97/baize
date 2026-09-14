"""AutoDream - Periodic memory dedup and consolidation via LLM + rule engine."""
import json
import sqlite3
import logging
import urllib.request
import urllib.error
from typing import Dict, List, Optional, Set
from datetime import datetime, timedelta

log = logging.getLogger("baize")

DISTILL_PROMPT = """你是一个记忆蒸馏系统。分析这批记忆并识别：

1. **重复项** — 含义/内容几乎相同的记忆。较新的应取代较旧的。
2. **合并候选** — 覆盖相关主题且可合并为更丰富事实的记忆。
3. **关键蒸馏事实** — 从这批记忆中需要保留的最重要事实。

只返回 JSON 对象（不要 markdown，不要解释）：

{{
  "superseded": [完全或近似重复的记忆 ID 列表],
  "distilled": [
    {{
      "keep_id": <保留的记忆 ID>,
      "merge_ids": [合并到其中的记忆 ID 列表],
      "merged_content": "<合并后的文本>",
      "reason": "<合并原因>"
    }}
  ],
  "candidates": [
    {{"keep_id": <ID>, "other_id": <ID>, "similarity": <0.0-1.0 相似度估计>}}
  ]
}}

记忆（ID：内容）：
{memories}

只返回有效的 JSON — 不要前言，不要代码块。"""


class AutoDream:
    """Periodic memory consolidation — LLM first, rule engine as fallback.

    Pipeline:
    1. Try LLM distillation on batches of 20 memories (if api_key is configured)
    2. If LLM entirely fails, fall back to character-bigram Jaccard rule engine
    """

    def __init__(
        self,
        db_path: str,
        api_url: str = "",
        api_key: str = "",
        model: str = "",
    ):
        self.db_path = db_path
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    # ── LLM ─────────────────────────────────────────────────────────────────

    def _call_llm(self, prompt: str) -> Optional[Dict]:
        """Call LLM and extract structured JSON from response.

        Checks both ``content`` and ``reasoning_content`` fields (for reasoning
        models such as DeepSeek-R1 / QwQ that emit JSON in the reasoning trace).
        """
        try:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            payload = json.dumps({
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 4096,
            }).encode("utf-8")

            req = urllib.request.Request(
                f"{self.api_url}/chat/completions",
                data=payload,
                headers=headers,
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read())

            choice = result["choices"][0]["message"]
            content = choice.get("content", "")
            reasoning = choice.get("reasoning_content", "")

            # Prefer content, fall back to reasoning_content
            text = content if content.strip() else reasoning
            if not text.strip():
                log.warning("AutoDream: LLM returned empty content and reasoning_content")
                return None

            # Strip markdown code fences if present
            text = text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                # Generic fence — try the last block
                parts = text.split("```")
                if len(parts) >= 3:
                    text = parts[1 if parts[0].strip() == "" else -2].strip()

            # Locate outermost JSON object
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])

            log.warning("AutoDream: no JSON object found in LLM response")
            return None

        except Exception as e:
            log.warning(f"AutoDream LLM call failed: {e}")
            return None

    # ── similarity (rule engine) ────────────────────────────────────────────

    @staticmethod
    def _bigrams(s: str) -> Set[str]:
        """字符 bigram 集合（C5: 供 Jaccard 相似度与倒排剪枝共用）。"""
        if not s:
            return set()
        return {s[i:i+2] for i in range(len(s) - 1)}

    @staticmethod
    def _jaccard_similarity(a: str, b: str) -> float:
        """Character bigram Jaccard similarity (handles Chinese text well)."""
        if not a or not b:
            return 0.0

        set_a, set_b = AutoDream._bigrams(a), AutoDream._bigrams(b)
        intersection = set_a & set_b
        union = set_a | set_b
        return len(intersection) / len(union) if union else 0.0

    @staticmethod
    def _coerce_id(val) -> Optional[int]:
        """LLM 返回的 id 规范化（可能为 int/str/float），非法值返回 None（D2）。"""
        try:
            return int(val)
        except (TypeError, ValueError):
            return None

    # ── rule engine dedup ──────────────────────────────────────────────────

    def _rule_engine_dedup(self, memories: List[Dict], user_id: str = "default") -> Dict:
        """Run Jaccard dedup on a batch of memories. Returns counts dict.

        D3: 传入 user_id，_mark_superseded / _store_candidates 校验归属。
        """
        results = {"superseded": 0}

        # Sort newest-first so older dupes are superseded
        sorted_mems = sorted(memories, key=lambda m: m["id"], reverse=True)
        rule_superseded: Set[int] = set()

        # Near-duplicates (Jaccard > 0.9)
        for i, mem in enumerate(sorted_mems):
            if mem["id"] in rule_superseded:
                continue
            for j in range(i + 1, len(sorted_mems)):
                other = sorted_mems[j]
                if other["id"] in rule_superseded:
                    continue
                sim = self._jaccard_similarity(mem["content"], other["content"])
                if sim > 0.9:
                    rule_superseded.add(other["id"])
                    if self._mark_superseded(
                        other["id"],
                        f"duplicate (Jaccard={sim:.2f}) of memory {mem['id']}",
                        user_id,
                    ):
                        results["superseded"] += 1
                    log.info(
                        f"AutoDream: superseded {other['id']} "
                        f"(dup of {mem['id']}, J={sim:.2f})"
                    )

        # Similar pairs (0.7 < Jaccard ≤ 0.9) → store as candidates
        active = [m for m in sorted_mems if m["id"] not in rule_superseded]
        candidates: List[Dict] = []
        for i in range(len(active)):
            for j in range(i + 1, len(active)):
                sim = self._jaccard_similarity(
                    active[i]["content"], active[j]["content"]
                )
                if 0.7 < sim <= 0.9:
                    candidates.append({
                        "keep_id": active[i]["id"],
                        "other_id": active[j]["id"],
                        "similarity": round(sim, 2),
                    })
        # C8: 落库前过滤本批已 superseded 的 other_id（先判为 candidate 后其
        # 可能被更高相似度对 supersede）
        candidates = [c for c in candidates if c["other_id"] not in rule_superseded]
        if candidates:
            log.info(
                f"AutoDream: found {len(candidates)} similar pairs "
                f"(Jaccard 0.7–0.9), stored for review"
            )
            self._store_candidates(candidates, user_id)

        return results

    # ── main entry point ───────────────────────────────────────────────────

    def run_distillation(self, days: int = 7, user_id: str = "default") -> Dict:
        """Run memory distillation — LLM first, rule engine as fallback.

        D3: 只处理 user_id 的记忆（_get_recent_memories 按 user_id 过滤，
        写入前 _mark_superseded / _update_content / _store_candidates 校验归属）。
        """
        memories = self._get_recent_memories(days, user_id)
        if not memories:
            return {"status": "no_memories", "processed": 0}

        log.info(f"AutoDream: processing {len(memories)} memories from last {days} days (user={user_id})")

        results: Dict = {
            "merged": 0,
            "superseded": 0,
            "distilled": 0,
            "processed": len(memories),
            "llm_used": False,
            "rule_engine_used": False,
            # B4: 内容被合并更新的记忆（keep_id + 新 content），供上层重建向量
            "rebuilt": [],
        }

        # ── Phase 1: LLM distillation (batches of 20) ──────────────────────
        llm_success = False
        rule_fallback_used = False
        llm_superseded: Set[int] = set()

        if self.api_key and self.api_url:
            total_batches = (len(memories) - 1) // 20 + 1
            for i in range(0, len(memories), 20):
                batch = memories[i:i+20]
                # D2: 本批候选 id 集合，用于校验 LLM 返回的 id
                batch_ids: Set[int] = {m["id"] for m in batch}
                batch_text = "\n---\n".join(
                    f"[ID:{m['id']}] (importance={m.get('importance', 0.5):.1f}) {m['content']}"
                    for m in batch
                )
                prompt = DISTILL_PROMPT.format(memories=batch_text)

                llm_result = self._call_llm(prompt)
                if llm_result is None:
                    log.info(
                        f"AutoDream: LLM failed on batch {i//20 + 1}/{total_batches}, "
                        f"falling back to rule engine for this batch"
                    )
                    rule_results = self._rule_engine_dedup(batch, user_id)
                    results["superseded"] += rule_results["superseded"]
                    rule_fallback_used = True
                    continue

                llm_success = True

                # D2: 校验 superseded id 属于本批，否则丢弃并 warning
                for raw_sid in llm_result.get("superseded", []):
                    sid = self._coerce_id(raw_sid)
                    if sid is None:
                        log.warning(
                            f"AutoDream: LLM returned non-numeric superseded id {raw_sid!r}, dropped"
                        )
                        continue
                    if sid not in batch_ids:
                        log.warning(
                            f"AutoDream: LLM superseded id {sid} not in current batch, dropped"
                        )
                        continue
                    # 铁律保护：绝对禁止自动废弃核心资产轨道（identity / preference / rule）
                    target_mem = next((m for m in batch if m["id"] == sid), None)
                    if target_mem and target_mem.get("lane") in ("identity", "preference", "rule"):
                        log.warning(
                            f"AutoDream: Refusing to supersede protected lane '{target_mem.get('lane')}' for id {sid}"
                        )
                        continue

                    if sid not in llm_superseded:
                        llm_superseded.add(sid)
                        if self._mark_superseded(sid, "LLM: duplicate", user_id):
                            results["superseded"] += 1

                # D2: 校验 distilled keep_id/merge_ids 属于本批；rowcount==0 不计数
                for item in llm_result.get("distilled", []):
                    keep_id = self._coerce_id(item.get("keep_id"))
                    if keep_id is None:
                        log.warning("AutoDream: LLM distilled keep_id missing/non-numeric, dropped")
                        continue
                    if keep_id not in batch_ids:
                        log.warning(
                            f"AutoDream: LLM keep_id {keep_id} not in current batch, dropped"
                        )
                        continue
                    merged_text = item.get("merged_content", "")
                    if merged_text and self._update_content(keep_id, merged_text, user_id):
                        results["distilled"] += 1
                        results["merged"] += 1
                        # B4: 记录需重建向量的记忆，由上层（api_server）重建 float+i8 双写
                        results["rebuilt"].append({"keep_id": keep_id, "content": merged_text})
                    elif not merged_text:
                        log.warning(
                            f"AutoDream: distilled keep_id={keep_id} has empty merged_content, "
                            f"content update skipped"
                        )

                    # Mark merged-away memories as superseded
                    for mid in item.get("merge_ids", []):
                        mid = self._coerce_id(mid)
                        if mid is None or mid not in batch_ids:
                            log.warning(
                                f"AutoDream: merge id {mid!r} not in current batch, dropped"
                            )
                            continue
                        if mid not in llm_superseded:
                            llm_superseded.add(mid)
                            if self._mark_superseded(
                                mid, f"LLM: merged into {keep_id}", user_id
                            ):
                                results["superseded"] += 1

                log.info(
                    f"AutoDream: LLM batch {i//20 + 1}/{(len(memories)-1)//20 + 1} "
                    f"→ {len(llm_result.get('superseded', []))} superseded, "
                    f"{len(llm_result.get('distilled', []))} distilled"
                )

        results["llm_used"] = llm_success

        # ── Phase 2: Full rule-engine pass (only if neither LLM nor per-batch
        #    fallback ran — meaning api_key/api_url was unavailable entirely) ────
        if not llm_success and not rule_fallback_used:
            results["rule_engine_used"] = True
            log.info("AutoDream: LLM unavailable, running full rule engine pass")
            rule_results = self._rule_engine_dedup(memories, user_id)
            results["superseded"] += rule_results["superseded"]

        log.info(f"AutoDream complete: {results}")
        return {"status": "ok", **results}

    # ── session-level fast consolidation (P1-3) ─────────────────────────────

    def run_session_consolidation(self, minutes: int = 30,
                                  dup_threshold: float = 0.85,
                                  cand_threshold: float = 0.70,
                                  user_id: str = "default") -> Dict:
        """P1-3: 会话级快速合并 — 对最近 N 分钟写入的记忆做轻量去重/合并。

        参考 LycheeMem 的会话级 consolidation：不用 LLM（规则引擎 Jaccard），
        毫秒级完成，适合每次会话结束后快速收敛。与 AutoDream（7 天级深度
        蒸馏）互补。

        Args:
            minutes: 回顾最近多少分钟的写入
            dup_threshold: Jaccard ≥ 此值 → 直接合并（新者胜，旧者 superseded）
            cand_threshold: 高于此值但低于 dup_threshold → 存候选待审
            user_id: D3 限定只处理该用户的记忆

        Returns:
            {"status": "ok", "window_min": 30, "scanned": N,
             "merged": M, "candidates": K}

        C4: 参数钳制——非数值抛 ValueError（由 API 层转 400）；越界值钳到安全区间
        （dup_threshold∈[0,1]、cand_threshold∈[0,dup_threshold]、minutes≥1），
        防止 dup_threshold=-1 整窗互相 supersede、cand_threshold 越界污染候选表、
        minutes 为负恒空。
        C5: bigram 倒排剪枝——只对共享 ≥1 bigram 的对计算 Jaccard，把窗口内
        两两 O(n²) 降到 O(总 bigram 数 + 实际相近对)；不共享 bigram 的对
        Jaccard 必为 0，跳过是精确的。
        """
        # C4: 参数钳制
        try:
            minutes = int(minutes)
            dup_threshold = float(dup_threshold)
            cand_threshold = float(cand_threshold)
        except (TypeError, ValueError):
            raise ValueError(
                "invalid consolidation parameters: "
                "minutes/dup_threshold/cand_threshold must be numeric"
            )
        minutes = max(1, minutes)
        dup_threshold = max(0.0, min(1.0, dup_threshold))
        cand_threshold = max(0.0, min(dup_threshold, cand_threshold))

        memories = self._get_recent_memories_minutes(minutes, user_id)
        if not memories:
            return {"status": "no_memories", "scanned": 0, "merged": 0, "candidates": 0}

        log.info(f"SessionConsolidation: scanning {len(memories)} memories from last {minutes} min (user={user_id})")

        # 新者优先（id 大 = 新），重复时保留新的
        sorted_mems = sorted(memories, key=lambda m: m["id"], reverse=True)
        mem_by_id = {m["id"]: m for m in sorted_mems}
        superseded: Set[int] = set()
        candidates: List[Dict] = []

        # C5: bigram → ids 倒排索引
        bigram_index: Dict[str, Set[int]] = {}
        for m in sorted_mems:
            for bg in self._bigrams(m["content"]):
                bigram_index.setdefault(bg, set()).add(m["id"])

        for i, mem in enumerate(sorted_mems):
            if mem["id"] in superseded:
                continue
            # 与 mem 共享 ≥1 bigram 的候选（排除自身）
            cand_ids: Set[int] = set()
            for bg in self._bigrams(mem["content"]):
                cand_ids |= bigram_index.get(bg, set())
            cand_ids.discard(mem["id"])
            for other_id in cand_ids:
                if other_id >= mem["id"]:  # 只处理更旧的（保证每对只比一次）
                    continue
                if other_id in superseded:
                    continue
                other = mem_by_id.get(other_id)
                if not other:
                    continue
                sim = self._jaccard_similarity(mem["content"], other["content"])
                if sim >= dup_threshold:
                    superseded.add(other["id"])
                    self._mark_superseded(
                        other["id"],
                        f"session-dup (Jaccard={sim:.2f}) of {mem['id']}",
                        user_id,
                    )
                    log.info(f"SessionConsolidation: merged {other['id']} into {mem['id']} (J={sim:.2f})")
                elif sim >= cand_threshold:
                    candidates.append({
                        "keep_id": mem["id"], "other_id": other["id"],
                        "similarity": round(sim, 2),
                    })

        # C8: 落库前过滤 other_id ∈ 本批 superseded 的 pair（先判为 candidate 的
        # pair 其 other_id 随后可能被更高相似度对 supersede）
        candidates = [c for c in candidates if c["other_id"] not in superseded]
        if candidates:
            self._store_candidates(candidates, user_id)

        result = {
            "status": "ok",
            "window_min": minutes,
            "scanned": len(memories),
            "merged": len(superseded),
            "candidates": len(candidates),
        }
        log.info(f"SessionConsolidation complete: {result}")
        return result

    def _get_recent_memories_minutes(self, minutes: int, user_id: str = "default") -> List[Dict]:
        """Fetch active (non-superseded) memories from the last *minutes* minutes.

        D3: 按 user_id 过滤，避免跨用户合并/去重。
        """
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cutoff = (datetime.now() - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            "SELECT id, content, lane, importance, created_at "
            "FROM memories WHERE created_at > ? AND user_id = ? "
            "AND id NOT IN (SELECT memory_id FROM memory_states WHERE state='superseded') "
            "ORDER BY id DESC",
            (cutoff, user_id),
        )
        memories = []
        while True:
            rows = cur.fetchmany(500)
            if not rows:
                break
            memories.extend(dict(row) for row in rows)
        conn.close()
        return memories

    # ── db helpers ─────────────────────────────────────────────────────────

    def _get_recent_memories(self, days: int, user_id: str = "default") -> List[Dict]:
        """Fetch memories from the last *days* days.

        D3: 按 user_id 过滤，避免跨用户蒸馏。
        """
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            "SELECT id, content, lane, importance, created_at "
            "FROM memories WHERE created_at > ? AND user_id = ? ORDER BY id DESC",
            (cutoff, user_id),
        )
        memories = []
        while True:
            rows = cur.fetchmany(500)
            if not rows:
                break
            memories.extend(dict(row) for row in rows)
        conn.close()
        return memories

    def _mark_superseded(self, memory_id: int, reason: str, user_id: str = "default") -> bool:
        """Insert a 'superseded' state record for *memory_id*.

        D2/D3: 先确认目标记忆存在且属于 user_id，否则丢弃并记 warning，返回 False。
        """
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        try:
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM memories WHERE id = ?", (memory_id,))
            row = cur.fetchone()
            if not row:
                log.warning(f"AutoDream: skip supersede memory {memory_id}: not found")
                return False
            if row[0] != user_id:
                log.warning(
                    f"AutoDream: skip supersede memory {memory_id}: "
                    f"belongs to user '{row[0]}', not '{user_id}'"
                )
                return False
            cur.execute(
                "INSERT OR REPLACE INTO memory_states "
                "(memory_id, state, reason, source, updated_at) "
                "VALUES (?, 'superseded', ?, 'auto_dream', datetime('now','localtime'))",
                (memory_id, reason),
            )
            conn.commit()
            log.debug(f"AutoDream: marked memory {memory_id} as superseded: {reason}")
            return True
        finally:
            conn.close()

    def _update_content(self, memory_id: int, content: str, user_id: str = "default") -> bool:
        """Update a memory's content in-place (used for LLM-merged text).

        D2: rowcount==0（目标行不存在/未更新）时不视为成功，调用方不再计数。
        D3: 只允许更新属于 user_id 的记忆。
        """
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        try:
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM memories WHERE id = ?", (memory_id,))
            row = cur.fetchone()
            if not row:
                log.warning(f"AutoDream: skip content update memory {memory_id}: not found")
                return False
            if row[0] != user_id:
                log.warning(
                    f"AutoDream: skip content update memory {memory_id}: "
                    f"belongs to user '{row[0]}', not '{user_id}'"
                )
                return False
            cur.execute(
                "UPDATE memories SET content = ? WHERE id = ?",
                (content, memory_id),
            )
            if cur.rowcount == 0:
                log.warning(
                    f"AutoDream: content update no-op for memory {memory_id} (rowcount=0)"
                )
                return False
            conn.commit()
            log.debug(f"AutoDream: updated content of memory {memory_id}")
            return True
        finally:
            conn.close()

    @staticmethod
    def _owned_ids(conn, memory_ids, user_id: str) -> Set[int]:
        """C8: 批量反查给定 id 中属于 user_id 的子集（供 _store_candidates 校验）。"""
        ids = list(dict.fromkeys(memory_ids))
        if not ids:
            return set()
        owned: Set[int] = set()
        BATCH = 200
        for start in range(0, len(ids), BATCH):
            chunk = ids[start:start + BATCH]
            ph = ",".join("?" * len(chunk))
            cur = conn.cursor()
            cur.execute(
                f"SELECT id FROM memories WHERE id IN ({ph}) AND user_id = ?",
                list(chunk) + [user_id],
            )
            owned.update(r[0] for r in cur.fetchall())
        return owned

    @staticmethod
    def _ids_owned_by(conn, memory_ids, user_id: str) -> bool:
        """批量反查：给定 memory_ids 是否全部属于 user_id（D3）。

        C8: 内部委托 _owned_ids，避免重复查询逻辑。
        """
        if not memory_ids:
            return False
        owned = AutoDream._owned_ids(conn, memory_ids, user_id)
        return all(i in owned for i in memory_ids)

    def _store_candidates(self, candidates: List[Dict], user_id: str = "default"):
        """Persist high-similarity pairs to the *merge_suggestions* table.

        D3: merge_suggestions 无 user_id 列，写入前反查 memories 校验
        keep_id/other_id 均属于 user_id。
        C8: 批量归属校验（一次反查全部涉及 id）+ 批量查重（一次
        (keep_id, other_id) IN 查询），替代逐条 SELECT 的 N+1。
        """
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS merge_suggestions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    keep_id     INTEGER NOT NULL,
                    other_id    INTEGER NOT NULL,
                    similarity  REAL    NOT NULL,
                    reviewed    INTEGER DEFAULT 0,
                    created_at  TEXT    DEFAULT (datetime('now','localtime'))
                )
            """)
            # C8: 批量归属校验
            valid: List[Dict] = []
            if candidates:
                all_ids = []
                for c in candidates:
                    all_ids.append(c["keep_id"])
                    all_ids.append(c["other_id"])
                owned = self._owned_ids(conn, all_ids, user_id)
                valid = [c for c in candidates
                         if c["keep_id"] in owned and c["other_id"] in owned]
                if len(valid) < len(candidates):
                    log.warning(
                        f"AutoDream: skipped {len(candidates) - len(valid)} merge "
                        f"suggestion(s) with ids not owned by user '{user_id}'"
                    )

            # C8: 批量查重——一次 (keep_id, other_id) IN 查询取回已存在对
            existing: Set[tuple] = set()
            if valid:
                pairs = list(dict.fromkeys((c["keep_id"], c["other_id"]) for c in valid))
                BATCH = 200
                for start in range(0, len(pairs), BATCH):
                    chunk = pairs[start:start + BATCH]
                    ph = ",".join("(?,?)" for _ in chunk)
                    placeholders = [x for p in chunk for x in p]
                    existing.update(
                        (r[0], r[1]) for r in cur.execute(
                            f"SELECT keep_id, other_id FROM merge_suggestions "
                            f"WHERE (keep_id, other_id) IN ({ph})",
                            placeholders,
                        ).fetchall()
                    )

            inserted = 0
            for c in valid:
                if (c["keep_id"], c["other_id"]) in existing:
                    continue
                cur.execute(
                    "INSERT INTO merge_suggestions (keep_id, other_id, similarity) "
                    "VALUES (?, ?, ?)",
                    (c["keep_id"], c["other_id"], c["similarity"]),
                )
                inserted += 1
            conn.commit()
            return inserted
        finally:
            conn.close()
