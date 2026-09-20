"""Hybrid Recall - vector search (sqlite-vec) + FTS5 keyword search."""
import json
import math
import os
import sqlite3
import threading
import urllib.request
import logging
from typing import List, Dict, Optional
from datetime import datetime
import hashlib
import time
from collections import OrderedDict

from modules.decay import DecayManager
from modules.evolution import _chunked

try:
    import sqlite_vec
    HAS_VEC = True
except ImportError:
    HAS_VEC = False

log = logging.getLogger("baize")

# Voyage 主用（200M 免费）+ bge-m3 兜底（SiliconFlow 免费白嫖）
VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
VOYAGE_MODEL = "voyage-4-lite"
VOYAGE_KEY_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".voyage_key")
BGE_URL = "https://api.siliconflow.cn/v1/embeddings"
BGE_MODEL = "BAAI/bge-m3"
# 兼容旧常量（供外部引用）
EMBED_URL = VOYAGE_URL
EMBED_MODEL = VOYAGE_MODEL
EMBED_DIM = 1024

# bge-m3 L2 distance empirical maximum.
# Observed L2 distances for bge-m3 range ~0.0 (identical) to ~2.0 (dissimilar).
# Used to normalise distance into a 0-1 similarity score via 1.0 - distance / MAX_L2_DISTANCE.
# This is an empirical value, not a theoretical bound — bge-m3 embeddings are not
# strictly normalised to unit length, so the max distance is data-dependent.
MAX_L2_DISTANCE = 2.0

# E2: 三来源融合权重显式参数化（vector / FTS / graph 量纲对齐后加权融合）
VEC_WEIGHT = 0.5
FTS_WEIGHT = 0.3
GRAPH_WEIGHT = 0.2


class HybridRecall:
    """Combines vector similarity search (sqlite-vec) with FTS5 keyword search."""

    def __init__(self, db_path: str, embed_key_path: str, evolution=None):
        self.db_path = db_path
        # Voyage 主用（.voyage_key / BAIZE_VOYAGE_KEY），bge-m3 兜底（.embed_key / BAIZE_EMBED_KEY）
        voyage_key = os.environ.get("BAIZE_VOYAGE_KEY", "").strip()
        if not voyage_key and os.path.exists(VOYAGE_KEY_PATH):
            try:
                with open(VOYAGE_KEY_PATH) as f:
                    voyage_key = f.read().strip()
            except Exception:
                voyage_key = ""
        self.voyage_key = voyage_key
        # bge-m3 兜底 key（Linux 化：环境变量优先，文件兜底）
        env_key = os.environ.get("BAIZE_EMBED_KEY", "").strip()
        if env_key:
            self.embed_key = env_key
        else:
            try:
                with open(embed_key_path) as f:
                    self.embed_key = f.read().strip()
            except Exception:
                self.embed_key = ""
        # 兼容：self.embed_key 也作为 Voyage 调用的 key 别名（若 voyage_key 为空则回退）
        if not self.voyage_key:
            self.voyage_key = self.embed_key
        log.info(f"HybridRecall keys: voyage={'set' if self.voyage_key else 'missing'} bge={'set' if self.embed_key else 'missing'} (Voyage primary, bge fallback)")
        self.decay = DecayManager()
        self.evolution = evolution  # P2-2: 复用外部实例，避免每次 search 新建
        # P1-1: embedding LRU 缓存
        self._embed_cache: OrderedDict = OrderedDict()
        self._embed_cache_max = 256
        self._embed_cache_ttl = 3600
        # B3: LRU 缓存多线程访问保护（check-then-act 竞态）
        self._embed_lock = threading.Lock()
        self._init_vec()

    def _init_vec(self):
        """Initialize sqlite-vec virtual table + int8 量化表 if available."""
        if not HAS_VEC:
            return
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.execute("PRAGMA busy_timeout = 30000")
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_vec
                USING vec0(embedding float[{EMBED_DIM}])
            """)
            # P1-1: int8 量化表（numpy 余弦检索，4x 存储压缩）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_vec_i8 (
                    mem_id INTEGER PRIMARY KEY,
                    vec BLOB NOT NULL
                )
            """)
            conn.commit()
            conn.close()
            log.info("sqlite-vec initialized (float + int8 tables)")
        except Exception as e:
            log.warning(f"sqlite-vec init failed: {e}")

    @staticmethod
    def _quantize_int8(vector) -> bytes:
        """P1-1: float32 向量 → int8 量化 bytes（L2 归一化 × 127）。

        余弦相似度在量化后仍保留（符号+幅度 7bit 精度），存储 4x 压缩。
        B7: 实现抽取到 modules/quantize.quantize_int8，供本模块与迁移脚本共用。
        """
        from modules.quantize import quantize_int8
        return quantize_int8(vector)

    def _vector_search_i8(self, query: str, user_id: str, limit: int,
                          _skipped: Optional[List] = None) -> List[Dict]:
        """P1-1: int8 量化向量余弦检索（numpy，毫秒级，不依赖 MAX_L2 经验值）。

        优先于 sqlite-vec float32 检索（存储 4x 压缩）。A4 加固：
        - 按 user_id 预过滤（JOIN memories，memory_vec_i8 无 user_id 列）
        - np.argpartition 取 top-k（替代全排序 argsort）
        - 坏 blob（长度≠1024）跳过该行而非整路径回退
        - 空表/全坏 blob 安全返回 []，触发上层 fallback
        - `_skipped` 可选收集器：传入 list 时，被跳过的坏 blob mem_id 追加其中，
          供 _vector_search 判断是否需 float32 补齐（坏 blob 行 = 该记忆在
          int8 侧不可见，等同双写缺行）
        """
        import numpy as np
        vector = self._get_embedding(query, input_type="query")
        if not vector:
            return []
        q = np.array(vector, dtype=np.float32)
        q = q / (np.linalg.norm(q) + 1e-9)
        q8 = np.clip(np.round(q * 127), -127, 127).astype(np.int8)

        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.row_factory = sqlite3.Row
        try:
            # A4: 按 user_id 预过滤，缩小扫描集（memory_vec_i8 无 user_id 列 → JOIN）
            # B6: 排除 superseded 记忆，避免其向量在检索路径长期存活占用 top-k
            rows = conn.execute(
                """SELECT i.mem_id, i.vec
                   FROM memory_vec_i8 i
                   JOIN memories m ON m.id = i.mem_id
                   WHERE m.user_id = ?
                     AND m.id NOT IN (SELECT memory_id FROM memory_states WHERE state = 'superseded')""",
                (user_id,),
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            return []

        # A4: 坏 blob 跳过该行，记录 warning，不整路径回退
        valid = []
        for r in rows:
            if len(r["vec"]) != EMBED_DIM:
                log.warning(f"Bad i8 vec for mem {r['mem_id']}: len={len(r['vec'])}")
                if _skipped is not None:
                    _skipped.append(r["mem_id"])
                continue
            valid.append(r)
        if not valid:
            return []

        ids = [r["mem_id"] for r in valid]
        qf = q8.astype(np.float32)
        q_norm = np.linalg.norm(qf)

        # Batch matrix ops to cap peak memory (B: watermark control)
        BATCH = 2000
        sims = np.empty(len(valid), dtype=np.float32)
        for start in range(0, len(valid), BATCH):
            chunk = valid[start:start + BATCH]
            mat = np.frombuffer(b"".join(r["vec"] for r in chunk), dtype=np.int8) \
                .reshape(-1, EMBED_DIM).astype(np.float32)
            mat_norms = np.linalg.norm(mat, axis=1)
            sims[start:start + len(chunk)] = (mat @ qf) / (mat_norms * q_norm + 1e-9)
        sims = (sims + 1.0) / 2.0  # [-1,1] → [0,1]

        # 2026-09-17 第一刀：初筛过采样（Over-fetching），从 limit 提升至 max(limit * 5, 25)
        # 防止昨晚的新决策因微小向量分数劣势在初筛阶段被直接掐死在门槛外
        candidate_k = max(limit * 5, 25)
        k = min(candidate_k, len(sims))
        if k <= 0:
            return []
        if k < len(sims):
            top = np.argpartition(sims, -k)[-k:]
            top = top[np.argsort(sims[top])[::-1]]
        else:
            top = np.argsort(sims)[::-1]

        results = []
        if len(top):
            ph = ",".join("?" * len(top))
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.execute("PRAGMA busy_timeout = 30000")
            conn.row_factory = sqlite3.Row
            try:
                rows2 = conn.execute(
                    f"SELECT id, content, category, lane, importance, created_at, access_count, confirm_count "
                    f"FROM memories WHERE id IN ({ph}) AND user_id = ?",
                    [ids[i] for i in top] + [user_id],
                ).fetchall()
            finally:
                conn.close()
            row_map = {r["id"]: r for r in rows2}
            for i in top:
                row = row_map.get(ids[i])
                if not row:
                    continue
                created_ts = datetime.fromisoformat(row["created_at"]).timestamp()
                decay_factor = self.decay.get_score(
                    row["lane"], created_ts,
                    access_count=row["access_count"], importance=row["importance"],
                    confirm_count=row["confirm_count"] or 0,
                )
                final_score = float(sims[i]) * decay_factor
                results.append({
                    "id": row["id"], "content": row["content"],
                    "category": row["category"], "lane": row["lane"],
                    "importance": row["importance"],
                    "created_at": row["created_at"],
                    "relevance": round(float(sims[i]), 3),  # C7: 向量余弦相似度
                    "score": round(final_score, 3),
                })
        return results

    def search(self, query, user_id="default", limit=5, return_trace=False):
        """Hybrid search: vector 0.5 + FTS 0.3 + graph 0.2（importance 已由 decay.get_score 计入）。

        E2: 三来源各自量纲对齐到 [0,1] 后乘权重融合，不再被 vector 独大压死。
        v1.4: 引入 P0 追忆漏斗打点（search_trace）。
        """
        import time
        trace = {
            "query": query,
            "timings_ms": {},
            "stages": {}
        }
        t0 = time.perf_counter()
        results = {}

        # FTS5 keyword search (weight: FTS_WEIGHT) — 2026-09-17 初筛过采样
        t_fts = time.perf_counter()
        fts_limit = max(limit * 5, 25)
        fts_results = self._fts_search(query, user_id, fts_limit)
        trace["timings_ms"]["fts"] = round((time.perf_counter() - t_fts) * 1000, 2)
        trace["stages"]["fts_candidates"] = len(fts_results)
        for r in fts_results:
            rid = r["id"]
            results[rid] = {**r, "score": r.get("score", 0.5) * FTS_WEIGHT, "source": "fts"}

        # Vector search (weight: VEC_WEIGHT) — 2026-09-17 初筛过采样
        t_vec = time.perf_counter()
        vec_count = 0
        if HAS_VEC:
            try:
                vec_limit = max(limit * 5, 25)
                vec_results = self._vector_search(query, user_id, vec_limit)
                vec_count = len(vec_results)
                for r in vec_results:
                    rid = r["id"]
                    vec_score = r.get("score", 0.5) * VEC_WEIGHT
                    if rid in results:
                        results[rid]["score"] += vec_score
                        results[rid]["source"] = "hybrid"
                    else:
                        results[rid] = {**r, "score": vec_score, "source": "vector"}
            except Exception as e:
                log.warning(f"Vector search failed: {e}")
        trace["timings_ms"]["vector"] = round((time.perf_counter() - t_vec) * 1000, 2)
        trace["stages"]["vec_candidates"] = vec_count
        trace["stages"]["hybrid_merged"] = len(results)

        # C2: importance 不再显式叠加——decay.get_score 内部已含 importance
        # （score = importance * decay + access_boost），三条来源路径（FTS/vector/
        # graph）均已乘 decay_factor。此处再叠加 importance*0.2 会造成三重复计
        # （importance 被计入 3 次），高低 importance 的差异已由 decay_factor 体现。

        # 2026-09-18 第二刀：活跃记忆时效保底池（方案二 · Recent Pool）
        # 根治"最新决议文本不含查询关键词 → FTS/Vector 初筛（各 Top-100）即跌出
        # 候选集 → 永远享受不到 Recency Boost 而沉底"的系统性缺陷：最近 48h 内
        # 按 importance DESC, id DESC 的前 30 条活跃记忆无条件补入候选集，
        # 保底基准分 = importance * 0.4；已在候选集中的记忆保持原分数不变。
        # 纯 SQLite 毫秒级实现，评分量纲（Vector 0.5 + FTS 0.3 + Graph 0.2）不变。
        recent_pool_added = 0
        try:
            pool_now = time.time()
            # 注：库内 created_at 全量为空格分隔格式（'YYYY-MM-DD HH:MM:SS'），
            # isoformat() 产出的 'T' 分隔符会使同日边界记录被字符串比较误排除，
            # 故 SQL 侧用 REPLACE 对齐为空格格式后再比较。
            cutoff = datetime.fromtimestamp(pool_now - 172800).isoformat()
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.execute("PRAGMA busy_timeout = 30000")
            conn.row_factory = sqlite3.Row
            try:
                recent_rows = conn.execute(
                    """SELECT id, content, category, lane, importance, created_at,
                              access_count, confirm_count
                       FROM memories
                       WHERE user_id = ? AND created_at >= REPLACE(?, 'T', ' ')
                         AND id NOT IN (SELECT memory_id FROM memory_states WHERE state = 'superseded')
                       ORDER BY importance DESC, id DESC LIMIT 30""",
                    (user_id, cutoff),
                ).fetchall()
            finally:
                conn.close()
            for row in recent_rows:
                rid = row["id"]
                if rid in results:
                    continue  # 已在候选集中：保持原分数不变
                row_dict = dict(row)
                results[rid] = {
                    **row_dict,
                    "score": row_dict["importance"] * 0.4,
                    "source": "recent_pool",
                }
                recent_pool_added += 1
        except Exception as e:
            log.warning(f"Recent pool recall failed: {e}")
        trace["stages"]["recent_pool_added"] = recent_pool_added

        # P1-2: 图谱多跳扩展 — 沿 knowledge_evolution 关系边召回间接关联记忆
        t_graph = time.perf_counter()
        try:
            if self.evolution is None:
                from modules.evolution import EvolutionTracker
                self.evolution = EvolutionTracker(self.db_path)
            seed_ids = list(results.keys())[:limit]
            # D3: get_related 按 user_id 过滤图谱扩展，避免跨用户召回
            related = self.evolution.get_related(seed_ids, hops=2, user_id=user_id)
            if related:
                # relation 权重：enriches/confirms 强关联，replaces 中，challenges 弱
                rel_weight = {
                    "enriches": 0.6, "confirms": 0.6, "replaces": 0.5, "challenges": 0.3,
                }
                hop_decay = {1: 0.5, 2: 0.25}  # 跳数越远衰减越狠
                # B1: 批量取回关联记忆行（一次 IN 查询），替代逐条 _get_memory 连接
                related_rows = self._get_memories_by_ids(list(related.keys()), user_id)
                for rid, info in related.items():
                    if rid in results:
                        continue
                    row = related_rows.get(rid)
                    if not row:
                        continue
                    w = rel_weight.get(info["relation"], 0.4)
                    # C3: 关联记忆自身 age/importance 参与打分（decay.get_score），
                    # 陈旧关联记忆分数自然下降，不再被抬进 top-k。B2 的置信度连乘
                    # （info["confidence"]）保留，两者不冲突。
                    created_ts = datetime.fromisoformat(row["created_at"]).timestamp()
                    decay_factor = self.decay.get_score(
                        row["lane"], created_ts,
                        access_count=row.get("access_count", 0),
                        importance=row["importance"],
                        confirm_count=row.get("confirm_count") or 0,
                    )
                    # E2: 去掉 base_score 连乘（受 direct-hit 高分污染且量级不可控），
                    # 改为纯关系强度 graph_rel = rel_weight×hop_decay×confidence（0-1），
                    # 再乘 decay_factor 与 GRAPH_WEIGHT，与 FTS/vector 量纲对齐。
                    graph_rel = min(1.0, w * hop_decay.get(info["hop"], 0.2) * info["confidence"])
                    score = graph_rel * decay_factor * GRAPH_WEIGHT
                    results[rid] = {
                        "id": rid, "content": row["content"],
                        "category": row["category"], "lane": row["lane"],
                        "importance": row["importance"],
                        "created_at": row["created_at"],
                        "relevance": None,  # C7: 图谱路径无直接查询-记忆语义相似度
                        "score": round(score, 3), "source": f"graph:{info['relation']}",
                    }
        except Exception as e:
            log.warning(f"Graph expansion failed: {e}")
        finally:
            trace["timings_ms"]["graph"] = round((time.perf_counter() - t_graph) * 1000, 2)
            trace["stages"]["graph_expanded"] = len(results) - trace["stages"]["hybrid_merged"]

        # 2026-09-17 第一刀：绝对时效加性增益（Additive Recency Prior）
        # 让 24-48 小时内的最新真决议拥有确定性的反超加分，彻底消除 14 天前老黄历压制新决议的死穴
        now_ts = time.time()
        for r in results.values():
            try:
                c_ts = datetime.fromisoformat(r["created_at"]).timestamp()
                age_h = (now_ts - c_ts) / 3600.0
                recency_boost = 0.0
                if age_h <= 24:
                    recency_boost = 0.25
                elif age_h <= 48:
                    recency_boost = 0.15
                elif age_h <= 168:
                    recency_boost = 0.05
                r["score"] = round(r["score"] + recency_boost, 3)
                r["recency_boost"] = recency_boost
            except Exception:
                pass

        sorted_results = sorted(results.values(), key=lambda x: x["score"], reverse=True)

        # Filter superseded memories (P2-2: 复用外部 evolution 实例)
        # B1: 批量判断 superseded，替代逐条 is_superseded（每条一次 SQLite 连接）
        superseded_count = 0
        try:
            if self.evolution is None:
                from modules.evolution import EvolutionTracker
                self.evolution = EvolutionTracker(self.db_path)
            ids = [r["id"] for r in sorted_results]
            superseded = self.evolution.is_superseded_batch(ids)
            before_filter = len(sorted_results)
            sorted_results = [r for r in sorted_results if r["id"] not in superseded]
            superseded_count = before_filter - len(sorted_results)
        except Exception:
            pass

        trace["stages"]["superseded_filtered"] = superseded_count
        trace["stages"]["final_candidates"] = len(sorted_results)
        trace["timings_ms"]["total_recall"] = round((time.perf_counter() - t0) * 1000, 2)

        final_res = sorted_results[:limit]
        if return_trace:
            return {"results": final_res, "trace": trace}
        return final_res

    def _get_memories_by_ids(self, ids, user_id: str) -> Dict[int, Dict]:
        """B1: 批量读取记忆行（WHERE id IN (...)，分批防变量数上限）。

        供图谱扩展一次取回全部关联记忆，替代逐条 _get_memory（每条一次连接）。
        返回 {id: row_dict}；空/异常返回 {}。
        """
        if not ids:
            return {}
        uniq = list(dict.fromkeys(ids))
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            mems: Dict[int, Dict] = {}
            for chunk in _chunked(uniq, 200):
                ph = ",".join("?" * len(chunk))
                cur.execute(
                    "SELECT id, content, category, lane, importance, created_at, access_count, confirm_count "
                    f"FROM memories WHERE id IN ({ph}) AND user_id = ?",
                    list(chunk) + [user_id],
                )
                for row in cur.fetchall():
                    mems[row["id"]] = dict(row)
            return mems
        except Exception:
            return {}
        finally:
            conn.close()

    def _fts_search(self, query: str, user_id: str, limit: int) -> List[Dict]:
        """SQLite FTS5 trigram search — 相关度 = 绝对量度 × 位次衰减，再乘衰减。

        C1 修复：原实现对候选集内 BM25 rank 做 min-max 归一化，任何查询只要
        命中 ≥1 条，最优那条 relevance 恒为 1.0（弱匹配被虚高）。现改为不依赖
        候选集内相对排名的基准：
        - hit_factor = H/(H+alpha)：命中数绝对量度（alpha≈10），弱查询命中少
          整体压低，不再"恒 1.0"；
        - rank_norm = |rank|/(|rank|+H+1)：FTS5 BM25 rank 是负分（绝对值越小
          越相关），映射到 (0,1)，与候选集内其它成员无关；
        - relevance = exp(-k * rank_norm) * hit_factor（k≈2），恒 < 1.0，
          强命中分数显著高于弱命中。
        """
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.execute("PRAGMA busy_timeout = 30000")
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.cursor()
                q = (query or "").strip()
                if not q:
                    return []

                # 防御中文短查询：trigram 分词对 <3 字符（中文/单词）无法匹配，
                # MATCH 恒返回 0 → 优雅降级为 memories.content 的 LIKE 召回。
                if len(q) < 3:
                    like_pat = f"%{q}%"
                    total_hits = cur.execute(
                        """SELECT count(*) FROM memories m
                           WHERE m.content LIKE ? AND m.user_id = ?
                             AND m.id NOT IN (SELECT memory_id FROM memory_states WHERE state = 'superseded')""",
                        (like_pat, user_id),
                    ).fetchone()[0]
                    if not total_hits:
                        return []
                    rows = cur.execute(
                        """SELECT m.id, m.content, m.category, m.lane, m.importance,
                                  m.created_at, m.access_count, m.confirm_count
                           FROM memories m
                           WHERE m.content LIKE ? AND m.user_id = ?
                             AND m.id NOT IN (SELECT memory_id FROM memory_states WHERE state = 'superseded')
                           ORDER BY m.id DESC LIMIT ?""",
                        (like_pat, user_id, limit),
                    ).fetchall()
                    alpha = 5.0
                    k = 2.0
                    hit_factor = total_hits / (total_hits + alpha)
                    results = []
                    for row in rows:
                        created = datetime.fromisoformat(row["created_at"]).timestamp()
                        decay_score = self.decay.get_score(row["lane"], created,
                                                            access_count=row["access_count"],
                                                            importance=row["importance"],
                                                            confirm_count=row["confirm_count"] or 0)
                        # LIKE 无 BM25 rank，取中性位次 rank_norm=0.5 保持量纲一致
                        relevance = math.exp(-k * 0.5) * hit_factor
                        results.append({
                            "id": row["id"], "content": row["content"],
                            "category": row["category"], "lane": row["lane"],
                            "importance": row["importance"],
                            "created_at": row["created_at"],
                            "relevance": round(relevance, 3),
                            "score": round(relevance * decay_score, 3),
                        })
                    return results

                # 限定 content 列检索：用户未显式指定列（无冒号）时，
                # 采用两段式策略：
                # 1. 优先尝试精确短语匹配 content : "{escaped}"
                # 2. 若精确短语为 0 命中（常见于自然语言长句），自动回退为关键词/词元 OR 召回，
                #    彻底消除长句提问时 FTS 候选恒为 0 导致的单引擎跛脚问题。
                if ":" in q:
                    fts_query = q
                    fts_candidates = [fts_query]
                else:
                    escaped = q.replace('"', '""')
                    phrase_query = f'content : "{escaped}"'
                    
                    # 构造关键词 OR 兜底查询
                    import re
                    en_words = re.findall(r'[a-zA-Z0-9_]{2,}', q)
                    cn_chunks = re.findall(r'[\u4e00-\u9fa5]+', q)
                    raw_terms = list(en_words)
                    for chunk in cn_chunks:
                        if len(chunk) == 3 or len(chunk) == 4:
                            raw_terms.append(chunk)
                        elif len(chunk) > 4:
                            for idx in range(len(chunk) - 2):
                                raw_terms.append(chunk[idx:idx+3])
                    stopwords = {'为什么', '怎么', '什么', '可以', '这个', '那个', '因为', '所以', '如果', '但是', '以前', '明明', '显示', '用户', '助手'}
                    filtered_terms = [t for t in dict.fromkeys(raw_terms) if t not in stopwords and len(t) >= 2]
                    # 优先满足 trigram 的项（长>=3 或 英文/数字）
                    trigram_terms = [t for t in filtered_terms if len(t) >= 3 or re.match(r'^[a-zA-Z0-9_]+$', t)]
                    use_terms = trigram_terms if trigram_terms else filtered_terms
                    if use_terms:
                        top_terms = use_terms[:8]
                        fallback_clause = ' OR '.join(f'"{t}"' for t in top_terms)
                        fallback_query = f'content : ({fallback_clause})'
                        fts_candidates = [phrase_query, fallback_query]
                    else:
                        fts_candidates = [phrase_query]

                total_hits = 0
                fts_query = fts_candidates[0]
                for candidate_query in fts_candidates:
                    cnt = cur.execute(
                        """SELECT count(*) FROM memories_fts f
                           JOIN memories m ON f.rowid = m.id
                           WHERE memories_fts MATCH ? AND m.user_id = ?
                             AND m.id NOT IN (SELECT memory_id FROM memory_states WHERE state = 'superseded')""",
                        (candidate_query, user_id),
                    ).fetchone()[0]
                    if cnt > 0:
                        total_hits = cnt
                        fts_query = candidate_query
                        break

                if not total_hits:
                    return []
                cur.execute(
                    """SELECT m.id, m.content, m.category, m.lane, m.importance,
                              m.created_at, m.access_count, m.confirm_count, f.rank AS fts_rank
                       FROM memories_fts f
                       JOIN memories m ON f.rowid = m.id
                       WHERE memories_fts MATCH ? AND m.user_id = ?
                         AND m.id NOT IN (SELECT memory_id FROM memory_states WHERE state = 'superseded')
                       ORDER BY f.rank LIMIT ?""",
                    (fts_query, user_id, limit)
                )
                rows = cur.fetchall()
                if not rows:
                    return []

                # E2: alpha 10→5，减少弱查询过度压制（hit_factor = H/(H+alpha)）
                alpha = 5.0
                k = 2.0
                hit_factor = total_hits / (total_hits + alpha)

                results = []
                for row in rows:
                    created = datetime.fromisoformat(row["created_at"]).timestamp()
                    decay_score = self.decay.get_score(row["lane"], created,
                                                        access_count=row["access_count"],
                                                        importance=row["importance"],
                                                        confirm_count=row["confirm_count"] or 0)
                    rank_norm = abs(row["fts_rank"]) / (abs(row["fts_rank"]) + total_hits + 1.0)
                    relevance = math.exp(-k * rank_norm) * hit_factor
                    score = relevance * decay_score
                    results.append({
                        "id": row["id"], "content": row["content"],
                        "category": row["category"], "lane": row["lane"],
                        "importance": row["importance"],
                        "created_at": row["created_at"],
                        "relevance": round(relevance, 3),
                        "score": round(score, 3),
                    })
                return results
            finally:
                conn.close()
        except Exception:
            return []

    def _vector_search(self, query: str, user_id: str, limit: int) -> List[Dict]:
        """Vector similarity search — P1-1: 优先 int8 量化表（numpy 余弦）。

        A1 修复：int8 结果不足 limit 时用 float32 补齐并合并（不再短路返回），
        双写缺行（float 成功 / int8 失败）的记忆不会永久不可见；
        int8 路径异常时降级 float 路径（现有逻辑保留）。
        A4 联动：int8 侧跳过坏 blob 行（该记忆 int8 不可见，等同双写缺行）时
        同样触发 float32 补齐，避免坏 blob 记忆永久不可见。
        """
        i8_results = []
        i8_ok = False
        i8_skipped = []
        try:
            i8_results = self._vector_search_i8(query, user_id, limit, _skipped=i8_skipped)
            i8_ok = True
        except Exception as e:
            log.warning(f"int8 vector search failed, fallback to sqlite-vec: {e}")

        # A1: int8 不足 limit 或跳过坏 blob 行时，用 float32 补齐
        f32_results = []
        if not i8_ok or len(i8_results) < limit or i8_skipped:
            try:
                f32_results = self._vector_search_f32(query, user_id, limit * 2)
            except Exception as e:
                log.warning(f"float32 vector search failed: {e}")

        # 合并：同 id 保留更高分，按分数降序取 limit
        best = {}
        for r in list(i8_results) + f32_results:
            rid = r["id"]
            if rid not in best or r["score"] > best[rid]["score"]:
                best[rid] = r
        merged = sorted(best.values(), key=lambda x: x["score"], reverse=True)
        return merged[:limit]

    def _vector_search_f32(self, query: str, user_id: str, limit: int) -> List[Dict]:
        """sqlite-vec float32 检索（A1: 独立方法，供 int8 不足 limit 或跳过坏 blob 时补齐）。"""
        if not HAS_VEC:
            return []
        vector = self._get_embedding(query, input_type="query")
        if not vector:
            return []

        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        try:
            # Check if vec table has data (sqlite-vec returns empty on empty table, no crash)
            cur = conn.cursor()
            count = cur.execute("SELECT count(*) FROM memory_vec").fetchone()[0]
            if count == 0:
                return []

            # Search
            search_limit = max(1, limit)
            cur.execute(
                "SELECT rowid, distance FROM memory_vec WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
                (json.dumps(vector), search_limit)
            )
            vec_results = cur.fetchall()

            if not vec_results:
                return []

            # F2: 一次性取回全部 rowid 对应记忆行（批量 IN 查询），替代逐条 cur2 单查
            ids = [rowid for rowid, _ in vec_results]
            rows = self._get_memories_by_ids(ids, user_id)

            # F2: superseded 批量排除（复用 evolution 实例，参考 search() 的懒加载模式）
            try:
                if self.evolution is None:
                    from modules.evolution import EvolutionTracker
                    self.evolution = EvolutionTracker(self.db_path)
                superseded = self.evolution.is_superseded_batch(ids)
            except Exception:
                superseded = set()

            results = []
            for rowid, distance in vec_results:
                row = rows.get(rowid)
                if not row:
                    continue
                # B6: 排除 superseded 记忆，避免其向量在检索路径长期存活
                if rowid in superseded:
                    continue
                # Convert L2 distance to similarity score (0-1, higher = more similar)
                score = max(0.0, 1.0 - distance / MAX_L2_DISTANCE)
                # Apply decay
                created_ts = datetime.fromisoformat(row["created_at"]).timestamp()
                decay_factor = self.decay.get_score(
                    row["lane"], created_ts, access_count=row["access_count"], importance=row["importance"],
                    confirm_count=row.get("confirm_count") or 0,
                )
                final_score = score * decay_factor
                results.append({
                    "id": row["id"], "content": row["content"],
                    "category": row["category"], "lane": row["lane"],
                    "importance": row["importance"],
                    "created_at": row["created_at"],
                    "relevance": round(score, 3),  # C7: 余弦/距离相关度
                    "score": round(final_score, 3),
                })

            return results
        finally:
            conn.close()

    def store_vector(self, mem_id: int, text: str) -> bool:
        """Store a vector for a memory entry.

        A1 修复：float 与 int8 双写放在同一事务，任一失败整体回滚（不再
        float 成功 / int8 失败后静默提交，导致 int8 缺行永久不可见）。
        返回 True 成功 / False 失败（失败已记录 warning）。
        """
        if not HAS_VEC:
            return False
        vector = self._get_embedding(text, input_type="document")
        if not vector:
            return False
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.execute("PRAGMA busy_timeout = 30000")
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            # vec0 虚表不支持 INSERT OR REPLACE，主键存在时会抛 UNIQUE 异常，
            # 先安全删除旧行再插入，确保更新已有记忆时能顺利重建向量。
            conn.execute("DELETE FROM memory_vec WHERE rowid = ?", (mem_id,))
            conn.execute(
                "INSERT INTO memory_vec(rowid, embedding) VALUES (?, ?)",
                (mem_id, json.dumps(vector))
            )
            # P1-1: 双写 int8 量化向量（numpy 检索用）——同事务，任一失败回滚
            conn.execute(
                "INSERT OR REPLACE INTO memory_vec_i8(mem_id, vec) VALUES (?, ?)",
                (mem_id, self._quantize_int8(vector))
            )
            conn.commit()
            return True
        except Exception as e:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            log.warning(f"VSS store failed for mem {mem_id}: {e}")
            return False
        finally:
            if conn is not None:
                conn.close()

    def _get_embedding(self, text: str, input_type: Optional[str] = None) -> Optional[List[float]]:
        """Voyage 主用 + bge-m3 兜底（P1-1: LRU 缓存）。

        B3: check-then-act 竞态加锁——缓存读取/淘汰在 _embed_lock 保护下执行，
        网络请求在锁外执行，避免多线程下对同一文本重复调 embedding API。
        双保险：Voyage 异常/限流/余额用尽 → 静默切 bge-m3 重试，LRU 缓存命中率高时几乎零开销。
        """
        input_mode = input_type or "document"
        key = hashlib.sha256(f"{input_mode}:{text}".encode("utf-8")).hexdigest()
        with self._embed_lock:
            entry = self._embed_cache.get(key)
            if entry:
                ts, vec = entry
                if time.time() - ts < self._embed_cache_ttl:
                    self._embed_cache.move_to_end(key)
                    return vec
                del self._embed_cache[key]

        # 1) Voyage 主用（query/document 由调用方决定，默认 document）
        voyage_it = input_type if input_type in ("query","document") else "document"
        vec = self._fetch_embedding(text, VOYAGE_URL, VOYAGE_MODEL, self.voyage_key, input_type=voyage_it)
        if vec is not None:
            with self._embed_lock:
                self._embed_cache[key] = (time.time(), vec)
                while len(self._embed_cache) > self._embed_cache_max:
                    self._embed_cache.popitem(last=False)
            return vec
        # 2) bge-m3 兜底（免费白嫖，不挑）
        if self.embed_key and self.embed_key != self.voyage_key:
            log.warning("Voyage embedding failed, fallback to bge-m3")
            vec = self._fetch_embedding(text, BGE_URL, BGE_MODEL, self.embed_key, input_type=None)
            if vec is not None:
                with self._embed_lock:
                    self._embed_cache[key] = (time.time(), vec)
                    while len(self._embed_cache) > self._embed_cache_max:
                        self._embed_cache.popitem(last=False)
                return vec
        elif self.embed_key:
            # voyage_key 与 embed_key 同值时仍尝试一次 bge 路径（URL 不同）
            vec = self._fetch_embedding(text, BGE_URL, BGE_MODEL, self.embed_key, input_type=None)
            if vec is not None:
                with self._embed_lock:
                    self._embed_cache[key] = (time.time(), vec)
                    while len(self._embed_cache) > self._embed_cache_max:
                        self._embed_cache.popitem(last=False)
                return vec
        return None

    def _fetch_embedding(self, text: str, url: str, model: str, api_key: str, input_type: Optional[str] = None) -> Optional[List[float]]:
        """单次 embedding 拉取（不碰缓存），input_type 仅 Voyage 需要。"""
        if not api_key:
            return None
        payload: Dict = {"model": model, "input": [text]}
        if input_type is not None:
            payload["input_type"] = input_type
        if "voyage" in model.lower():
            payload["output_dimension"] = EMBED_DIM
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            result = json.loads(resp.read())
            return result["data"][0]["embedding"]
        except Exception as e:
            # 让上层决定是否 fallback，不在此喷日志（由 _get_embedding 统一 warning）
            log.debug(f"embedding fetch failed {model}: {e}")
            return None

    def find_duplicate(self, text: str, user_id: str = "default",
                       threshold: float = 0.05) -> Optional[Dict]:
        """P2-1/D3: 返回与文本最相似且距离 < threshold 的*该用户*已有记忆（如有）。

        memory_vec 无 user_id 列：子查询取 top-N 最近候选后 JOIN memories
        按 user_id 过滤，返回该用户最近的一条。
        """
        vector = self._get_embedding(text, input_type="document")
        if not vector:
            return None
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        cur = conn.cursor()
        try:
            # B6: 排除 superseded 记忆——被取代的记忆不应再作为"重复"拦截新写入
            cur.execute(
                """SELECT m.id AS id, v.distance AS distance FROM
                   (SELECT rowid, distance FROM memory_vec
                    WHERE embedding MATCH ? ORDER BY distance LIMIT 200) v
                   JOIN memories m ON m.id = v.rowid
                   WHERE m.user_id = ?
                     AND m.id NOT IN (SELECT memory_id FROM memory_states WHERE state = 'superseded')
                   ORDER BY v.distance LIMIT 1""",
                (json.dumps(vector), user_id),
            )
            row = cur.fetchone()
        except Exception:
            row = None
        finally:
            conn.close()
        if row and row[1] < threshold:
            return {"id": row[0], "distance": row[1]}
        return None
