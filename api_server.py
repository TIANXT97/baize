#!/usr/bin/env python3
"""白泽 (Bai Ze) API Server - independent memory service for AI agents."""
import ctypes
import gc
import os
import sys
import json
import re
import hashlib
import time
import sqlite3
import logging
import threading
import uuid
import urllib.request
from datetime import datetime
from contextlib import contextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules import (
    MemoryGate, FastPath, CoalesceManager,
    DecayManager, HybridRecall, LLMExtractor,
    EvolutionTracker, WALEngine, CoreMemory,
    AutoDream,
    Reranker,
)
from modules.coalesce import PROFILES

# sqlite-vec 扩展：memory_vec 是 vec0 虚拟表，任何 DELETE/查询都需先 load 扩展
# （get_db() 的普通连接不加载扩展，A2 修复前 /api/cleanup 的 vec DELETE 因此静默失败）
try:
    import sqlite_vec
    HAS_SQLITE_VEC = True
except ImportError:
    HAS_SQLITE_VEC = False

# ===== Config =====
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
DB_PATH = os.path.join(DATA_DIR, "facts.db")
EMBED_KEY_PATH = os.path.join(BASE_DIR, ".embed_key")
LLM_KEY_PATH = os.path.join(BASE_DIR, ".llm_key")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOGS_DIR, "api_server.log")),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("baize")

# ===== Load config =====
def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}

config = load_config()
PORT = int(os.environ.get("BAIZE_PORT", config.get("port", 8767)))
LLM_API_URL = config.get("llm_api_url", "http://127.0.0.1:8000/v1")
LLM_MODEL = config.get("llm_model", "mimo-v2.5")

# Coalesce profile mapping from config (used in /add endpoint)
_speed_config = config.get("_speed", {})
COALESCE_PROFILE_BY_SOURCE = _speed_config.get("coalesce_profile_by_source", {})
COALESCE_DEFAULT_PROFILE = _speed_config.get("coalesce_default_profile", "default")

# ===== Database =====
def init_db():
    """Initialize SQLite database with schema."""
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS memories (
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
            expires_at TEXT
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
            content, category, source,
            content='memories',
            content_rowid='id',
            tokenize='trigram'
        );

        CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
            INSERT INTO memories_fts(rowid, content, category, source)
            VALUES (new.id, new.content, new.category, new.source);
        END;

        CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, content, category, source)
            VALUES ('delete', old.id, old.content, old.category, old.source);
        END;

        CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, content, category, source)
            VALUES ('delete', old.id, old.content, old.category, old.source);
            INSERT INTO memories_fts(rowid, content, category, source)
            VALUES (new.id, new.content, new.category, new.source);
        END;

        CREATE TABLE IF NOT EXISTS coalesce_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT DEFAULT (datetime('now','localtime')),
            profile TEXT,
            messages_count INTEGER,
            waves_count INTEGER,
            saved_llm_calls INTEGER,
            llm_save_rate REAL
        );

        CREATE INDEX IF NOT EXISTS idx_memories_user_id ON memories(user_id, id);
        CREATE INDEX IF NOT EXISTS idx_memories_user_created ON memories(user_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_memory_states_state_mem ON memory_states(state, memory_id);
        CREATE INDEX IF NOT EXISTS idx_knowledge_evo_src ON knowledge_evolution(source_id);
        CREATE INDEX IF NOT EXISTS idx_knowledge_evo_tgt ON knowledge_evolution(target_id);
        CREATE INDEX IF NOT EXISTS idx_merge_sugg_keep ON merge_suggestions(keep_id, other_id);
    """)
    # 全库高频检索索引建好后，运行 ANALYZE 刷新查询规划器统计信息
    conn.execute("ANALYZE")
    # P2b: 幂等迁移——memories 表加 confirm_count 列（偏好/身份记忆置信度累积）
    cur = conn.cursor()
    cols = [row[1] for row in cur.execute("PRAGMA table_info(memories)").fetchall()]
    if "confirm_count" not in cols:
        cur.execute(
            "ALTER TABLE memories ADD COLUMN confirm_count INTEGER NOT NULL DEFAULT 0"
        )
        log.info("Migration: added memories.confirm_count column")
    # Reform: 幂等迁移——memories 表加 origin 字段
    if "origin" not in cols:
        cur.execute(
            "ALTER TABLE memories ADD COLUMN origin TEXT DEFAULT 'unknown'"
        )
        log.info("Migration: added memories.origin column")
    # Reform: 被否决事实墓碑表（rejected_values）
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rejected_values (
            content_hash TEXT PRIMARY KEY,
            content_pattern TEXT,
            reason TEXT,
            rejected_by_id INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()
    conn.close()
    log.info(f"Database initialized at {DB_PATH}")

@contextmanager
def get_db(write: bool = False):
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    try:
        if write:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# ===== Read API keys =====
def read_key(path, env_name=None):
    """Linux 化：环境变量优先（systemd 注入），文件兜底。"""
    if env_name:
        val = os.environ.get(env_name, "").strip()
        if val:
            return val
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    return ""

def read_dotenv_key(env_name, dotenv_path="/root/.hermes/.env"):
    """从 .env 文件读指定变量（模型与记忆共用同一个上游网关 key 时的正路）。

    2026-09-15：主 LLM 换到 10router 后，钥匙存在 Hermes 的 .env 里，
    不在 baize 的 systemd 环境里 —— 故须支持按变量名从 .env 取值。
    """
    if not env_name:
        return ""
    val = os.environ.get(env_name, "").strip()
    if val:
        return val
    try:
        if os.path.exists(dotenv_path):
            with open(dotenv_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    if k.strip() == env_name:
                        return v.strip().strip('"').strip("'")
    except Exception as e:
        log.warning(f"read_dotenv_key failed for {env_name}: {e}")
    return ""

embed_key = read_key(EMBED_KEY_PATH, "BAIZE_EMBED_KEY")
# 主键：优先 config 的 llm_key_env（可指向 .env，如 10ROUTER_API_KEY），
# 否则回退 systemd 注入的 BAIZE_LLM_KEY / 文件
_primary_key_env = os.environ.get("BAIZE_LLM_MAIN_KEY_ENV", "") or config.get("llm_key_env", "")
llm_key = (read_dotenv_key(_primary_key_env) if _primary_key_env else "") \
          or read_key(LLM_KEY_PATH, "BAIZE_LLM_KEY") \
          or os.environ.get("LLM_API_KEY", "")

# ===== Initialize modules =====
init_db()

evolution = EvolutionTracker(DB_PATH)
core_memory = CoreMemory(DB_PATH)
# WAL 治理：2MB 自动轮转 + 7 天归档保留。配置项未来可下沉到 config.json。
wal = WALEngine(
    os.path.join(DATA_DIR, "wal.jsonl"),
    retention_days=7,
    max_bytes=2 * 1024 * 1024,
)

gate = MemoryGate()
fastpath = FastPath()
decay = DecayManager()
recall = HybridRecall(
    db_path=DB_PATH,
    embed_key_path=EMBED_KEY_PATH,
    evolution=evolution,
) if embed_key else None
extract_cache_ttl_sec = _speed_config.get("extract_cache_ttl_sec", 3600)
extract_cache_max = _speed_config.get("extract_cache_max", 256)
# 2026-09-15：超时/上限可配 + 备用 LLM 端点（主端点整链失败时逐级降级，
# 避免历史 15s 硬超时把慢响应判死 → 静默灌原文垃圾）
extract_timeout_sec = int(_speed_config.get("extract_timeout_sec", 30))
extract_max_tokens = int(_speed_config.get("max_tokens", 2048))
_fallbacks = []
for _fb in (_speed_config.get("llm_fallbacks") or []):
    if not isinstance(_fb, dict):
        continue
    _fb_key = _fb.get("api_key") or read_dotenv_key(_fb.get("key_env", "")) \
              or os.environ.get(_fb.get("key_env", ""), "")
    if _fb.get("api_url") and _fb_key and _fb.get("model"):
        _fallbacks.append({"api_url": _fb["api_url"], "api_key": _fb_key,
                           "model": _fb["model"]})
        log.info(f"LLM fallback registered: {_fb['model']} @ {_fb['api_url']}")
    else:
        log.warning(f"LLM fallback skipped (incomplete config): {_fb.get('model')}")
extractor = LLMExtractor(api_url=LLM_API_URL, api_key=llm_key, model=LLM_MODEL,
                          cache_ttl_sec=extract_cache_ttl_sec, cache_max=extract_cache_max,
                          timeout_sec=extract_timeout_sec, max_tokens=extract_max_tokens,
                          fallbacks=_fallbacks) if llm_key else None

# Coalesce with auto-flush callback
def on_wave_flush(messages, profile, user_id="default"):
    """Called when a coalesce wave flushes. Extract facts from combined messages."""
    combined = "\n".join(messages)
    log.info(f"Wave flush: {len(messages)} msgs, profile={profile}, user_id={user_id}")
    # coalesce 是聚合的用户对话流，按 user 处理
    _store_extracted_facts(combined, source=f"coalesce:{profile}", user_id=user_id, msg_origin="user")

coalesce = CoalesceManager(flush_callback=on_wave_flush)


# Reranker — Voyage rerank-2.5-lite 主用 + bge-reranker-v2-m3 兜底（自动读 .voyage_key / BAIZE_VOYAGE_KEY 与 .embed_key）
reranker = Reranker()

auto_dream = AutoDream(
    db_path=DB_PATH,
    api_url=LLM_API_URL,
    api_key=llm_key,
    model=LLM_MODEL,
)

# Job tracking for async writes
jobs = {}
_JOBS_TTL = 30 * 60  # B8: 已完成/错误 job 保留 30 分钟

def _purge_old_jobs(ttl: int = _JOBS_TTL):
    """B8: 清理超过 *ttl* 秒的旧 job 条目，避免 jobs 字典只增不减。

    写入新 job 时调用（最坏情况下 jobs 峰值 ≈ 窗口内活跃 + 滞留 job 数）。
    """
    now = time.time()
    stale = [jid for jid, j in list(jobs.items())
             if j.get("created_at") and now - j["created_at"] > ttl]
    for jid in stale:
        jobs.pop(jid, None)
    if stale:
        log.info(f"Purged {len(stale)} stale jobs (> {ttl // 60} min)")

# Cache for /health embedding API probe (avoid hammering API on frequent health checks)
_embed_probe_cache = {"ts": 0.0, "ok": False}
_EMBED_PROBE_TTL = 30  # seconds — probe at most once per 30s

# ===== Core functions =====
def _batch_text_dedup(facts, threshold: float = 0.9):
    """B5: 批内文本级预筛 —— 与批内已保留 fact 高度相似（Jaccard）则跳过。

    对近似重复的 fact 不再逐个调 embedding 去重（每次一次 API 请求），
    只有批内去重后的幸存者才进入 find_duplicate（embedding 去重）。
    复用 auto_dream 的字符 bigram Jaccard，不引入新依赖。
    """
    kept = []
    accepted = []
    for f in facts:
        txt = (f.get("fact") or "").strip()
        if not txt:
            continue
        dup = False
        for a in accepted:
            if auto_dream._jaccard_similarity(txt, a) > threshold:
                dup = True
                break
        if dup:
            log.debug(f"Batch text dedup skip (Jaccard>{threshold}): {txt[:40]}")
            continue
        kept.append(f)
        accepted.append(txt)
    return kept

def _sync_core_memory_from_facts(facts, lane, user_id="default"):
    """F3: 将 identity 事实同步到 core_memory 的 user_profile 块。

    - 只同步 lane == 'identity' 的 fact 到 user_profile；
    - Reform: CoreMemory 物理铁闸——严禁非 user 亲陈事实进入 identity 广播区
    - 不覆盖已有内容，只 append 新信息（换行分隔）；重复 fact 不追加；
    - 超过 500 字符截断保留最新；block_name 是主键，INSERT OR REPLACE。
    """
    if lane != "identity" or not facts:
        return False
    _transient_keywords = ("当前会话", "当前档位", "当前模型", "使用的是")
    new_items = []
    for f in facts:
        txt = (f.get("fact") or "").strip()
        if not txt:
            continue
        if (f.get("category") or "") != lane:
            continue
        # Reform: 严禁非 user 亲陈事实进入 identity 广播区
        if f.get("origin") != "user":
            log.info(f"CoreMemory iron gate: blocked non-user origin fact: {txt[:40]}")
            continue
        # 过滤瞬态会话标签
        if any(kw in txt for kw in _transient_keywords):
            continue
        new_items.append(txt)
    if not new_items:
        return False
    try:
        with get_db() as conn:
            cur = conn.cursor()
            row = cur.execute(
                "SELECT content FROM core_memory WHERE block_name = 'user_profile' AND user_id = ?",
                (user_id,),
            ).fetchone()
            lines = [ln for ln in (row[0] or "").split("\n") if ln.strip()]
            # 矛盾清洗：新权威事实剔除已有矛盾行
            for txt in new_items:
                if "洋芋是男" in txt:
                    lines = [ln for ln in lines if "洋芋是女" not in ln]
                elif "洋芋是女" in txt:
                    lines = [ln for ln in lines if "洋芋是男" not in ln]
            added = 0
            for txt in new_items:
                if txt in lines:
                    continue
                lines.append(txt)
                added += 1
            if not added:
                return False
            # 安全行截断：按整行向前淘汰，绝不切断中间
            while lines and len("\n".join(lines)) > 500:
                lines.pop(0)
            merged = "\n".join(lines)
            cur.execute(
                "INSERT OR REPLACE INTO core_memory (block_name, user_id, content, updated_at) "
                "VALUES ('user_profile', ?, ?, datetime('now','localtime'))",
                (user_id, merged),
            )
            conn.commit()
        return True
    except Exception as e:
        log.warning(f"core_memory sync failed: {e}")
        return False

def _store_extracted_facts(text: str, source: str = "hermes", user_id: str = "default",
                           is_replay: bool = False, msg_origin: str = "user"):
    """Extract facts from text and store them.

    is_replay=True 时本函数正在消费历史 WAL pending，跳过 wal.append/mark_complete，
    避免重放失败时向 live WAL 写入同 key 新 pending 造成递归增殖。
    msg_origin: 消息来源角色打标（'user' / 'agent-inferred'）。
    """
    facts = []

    # Try fastpath first
    fp_result = fastpath.try_extract(text)
    if fp_result:
        facts.append(fp_result)

    # Try LLM extraction for longer text
    llm_failed = False
    llm_fail_reason = ""
    if extractor and len(text) > 20:
        try:
            llm_facts = extractor.extract(text, source=source)
            facts.extend(llm_facts)
        except Exception as e:
            llm_failed = True
            llm_fail_reason = str(e)
            log.error(f"LLM extraction unavailable, refusing raw-text fallback: {e}")

    if not facts:
        # Reform: 彻底铲除 fallback 生肉后门！LLM 返回 0 事实时绝对不落盘
        if llm_failed:
            log.error(
                f"Skip store: LLM chain unavailable for source={source} "
                f"(would have written raw text as fallback). reason={llm_fail_reason}"
            )
            return []
        log.info(
            f"LLM returned 0 facts, raw text strictly rejected. len={len(text.strip())}"
        )
        return []

    if not facts:
        return []

    # B5: 批内文本级预筛（先于 embedding 去重，减少 API 调用）
    facts = _batch_text_dedup(facts)

    # P2-1/D3: embedding 去重移出写事务——find_duplicate 内部发起外部 HTTP
    # 请求（Voyage/bge，可能耗时数十秒），绝不能在持有 SQLite 写锁时执行。
    # 进入写事务前先完成全部去重，得到纯净的 unique_facts 列表。
    # 2026-09-15 补闸：字面全等 SQL 直查兜底。find_duplicate 走向量最近邻，
    # 早期无向量条目（Voyage 换装前入库）/embedding API 失败时拦不住同句重写
    # （实测"用户叫TIAN"家族攒出 14 条字面/近字面重复）。零 API 成本。
    # 2026-09-15 复审修正：单连接批量 IN 查询（同文件 _get_memories_by_ids 样板），
    # 不再每条 fact 开一次连接。
    exact_dup_ids = {}
    stripped_texts = [(f, (f["fact"] or "").strip()) for f in facts]
    texts = [t for _, t in stripped_texts if t]
    # Reform: 入库前墓碑硬拦截——查 rejected_values 表
    import hashlib
    rejected_hashes = set()
    if texts:
        try:
            with get_db() as conn:
                ph = ",".join("?" * len(texts))
                for rid, rtext in conn.execute(
                    f"SELECT id, content FROM memories WHERE content IN ({ph}) AND user_id = ?",
                    texts + [user_id],
                ):
                    exact_dup_ids.setdefault(rtext, rid)
                # 查询墓碑表
                hash_list = []
                for t in texts:
                    norm = re.sub(r'[\s\W]+', '', t).lower()
                    hash_list.append(hashlib.sha256(norm.encode('utf-8')).hexdigest())
                ph2 = ",".join("?" * len(hash_list))
                for row in conn.execute(
                    f"SELECT content_hash FROM rejected_values WHERE content_hash IN ({ph2})",
                    hash_list,
                ):
                    rejected_hashes.add(row[0])
        except Exception as e:
            log.warning(f"Exact-text/tombstone dedup check failed: {e}")
    unique_facts = []
    for fact, txt in stripped_texts:
        if not txt:
            continue
        # Reform: 墓碑拦截
        norm = re.sub(r'[\s\W]+', '', txt).lower()
        content_hash = hashlib.sha256(norm.encode('utf-8')).hexdigest()
        if content_hash in rejected_hashes:
            log.warning(f"Rejected tombstone hit: #{txt[:40]} was rejected, drop.")
            continue
        hit_id = exact_dup_ids.get(txt)
        if hit_id:
            log.info(f"Exact-text dedup skip: #{hit_id} :: {txt[:40]}")
            continue
        if recall:
            try:
                dup = recall.find_duplicate(fact["fact"], user_id)
                if dup:
                    log.info(f"Dedup skip: #{dup['id']} d={dup['distance']:.3f} :: {fact['fact'][:40]}")
                    continue
            except Exception as e:
                log.warning(f"Dedup check failed: {e}")
        unique_facts.append(fact)
    facts = unique_facts

    stored = []
    vector_tasks = []
    # D1: WAL 记录 user_id，便于启动重放时按用户幂等重放（旧记录无 user_id → 按 default）
    if not is_replay:
        wal.append("store_facts", {"text": text, "source": source, "user_id": user_id})
    evolution_tasks = []
    with get_db() as conn:
        cur = conn.cursor()
        for fact in facts:
            # E1: category 归一化——若在 LANE_CONFIG 中直接用，否则 classify_lane 关键词兜底，再兜底 general
            lane = fact.get("category") if fact.get("category") in decay.LANE_CONFIG else decay.classify_lane(fact["fact"], fact.get("category", "general"))
            # Reform: 强制打标 origin
            fact_origin = msg_origin
            cur.execute(
                """INSERT INTO memories (user_id, category, content, lane, importance, source, origin)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, fact.get("category", "general"), fact["fact"],
                 lane, fact.get("importance", 0.5), fact.get("source", source), fact_origin)
            )
            mem_id = cur.lastrowid
            stored.append({"id": mem_id, "content": fact["fact"], "lane": lane})
            vector_tasks.append((mem_id, fact["fact"]))
            evolution_tasks.append((mem_id, fact["fact"]))

    # Store vectors AFTER closing the DB connection (avoids lock conflict)
    # 2026-08-12 修复：循环变量不可叫 text——会遮蔽函数参数 text，导致 L376
    # mark_complete 的 key 变成"最后一条 fact"而非对话原文，append 永远配不上
    # mark_complete（每轮提取留下一对孤儿账：孤儿 pending + 孤儿 complete）
    for mem_id, vec_text in vector_tasks:
        try:
            _store_vector(mem_id, vec_text)
        except Exception as e:
            log.warning(f"Vector store failed for mem {mem_id}: {e}")

    # Check evolution AFTER closing the DB connection (avoids lock conflict)
    # D3: evolution 按 user_id 隔离
    for mem_id, fact_text in evolution_tasks:
        try:
            evolution.check_evolution(fact_text, mem_id, user_id)
        except Exception as e:
            log.warning(f"Evolution check failed: {e}")

    if not is_replay:
        wal.mark_complete("store_facts", {"text": text, "source": source, "user_id": user_id})

    # F3: identity 事实同步到 core_memory user_profile（成功写入后，隔离失败）
    try:
        _sync_core_memory_from_facts(
            [{"fact": s["content"], "category": s["lane"], "origin": msg_origin} for s in stored], "identity",
            user_id=user_id,
        )
    except Exception as e:
        log.warning(f"core_memory sync failed: {e}")

    log.info(f"Stored {len(stored)} facts from {source}")
    return stored

def _store_vector(mem_id, text):
    """Store a vector via sqlite-vec."""
    if recall:
        log.info(f"Storing vector for mem {mem_id}: {text[:30]}")
        # A1: store_vector 返回 False 表示 float/int8 双写失败（已回滚），调用方感知
        if not recall.store_vector(mem_id, text):
            log.warning(f"Vector store failed for mem {mem_id} (float/int8 dual-write)")

def _rebuild_vectors(distill_result: dict):
    """B4: 蒸馏合并后 keep_id 的 content 已更新，旧向量语义过期 → 重建双写。

    AutoDream 与 HybridRecall 保持解耦：AutoDream 返回受影响 id，本函数在
    api_server 层调用 recall.store_vector 重建（float + int8 同事务双写）。
    """
    if not recall:
        return 0
    rebuilt = distill_result.get("rebuilt") or []
    done = 0
    for item in rebuilt:
        try:
            if recall.store_vector(item["keep_id"], item["content"]):
                done += 1
                log.info(f"Vector rebuilt for merged memory {item['keep_id']} (B4)")
            else:
                log.warning(f"Vector rebuild failed for merged memory {item['keep_id']} (B4)")
        except Exception as e:
            log.warning(f"Vector rebuild error for merged memory {item['keep_id']}: {e}")
    return done

# ===== D1: WAL startup replay =====
def _memory_exists(content: str, user_id: str) -> bool:
    """幂等预检：按 content+user_id 精确判断记忆是否已存在。"""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM memories WHERE content = ? AND user_id = ? LIMIT 1",
            (content, user_id),
        )
        return cur.fetchone() is not None

def _replay_wal_pending(wal_engine, pending):
    """D1: 启动时真正重放 WAL pending 操作（走正常写入路径，幂等，失败不阻塞启动）。

    - store_facts：先按 content+user_id 精确去重预检，已存在 → 直接 mark_complete；
      否则走 _store_extracted_facts 重新执行写入（内部含 find_duplicate 去重 +
      vector/evolution 全链路），成功后 mark_complete。单条失败仅记 warning，
      保留 pending 待下次启动重试，不阻塞服务启动。
    - 未知 op：记 warning 跳过（仅审计，不清理）。
    """
    stats = {"replayed": 0, "already_present": 0, "failed": 0, "skipped": 0}
    if not pending:
        return stats

    for entry in pending:
        op = entry.get("op")
        # 防爆盾：脏数据 data 非 dict（如字符串/None）时统一降级为空 dict，
        # 避免 data.get 抛 AttributeError 阻断整个服务启动。
        data = entry.get("data") if isinstance(entry.get("data"), dict) else {}
        try:
            if op == "store_facts":
                text = str(data.get("text") or "").strip()
                source = data.get("source") or "hermes"
                # 旧记录未记录 user_id → 历史 coalesce/hermes 写入均为 default
                user_id = data.get("user_id") or "default"
                if not text:
                    log.warning(f"WAL replay: empty store_facts payload, mark complete: {data}")
                    stats["skipped"] += 1
                    wal_engine.mark_complete(op, data)
                    continue
                if _memory_exists(text, user_id):
                    stats["already_present"] += 1
                    wal_engine.mark_complete(op, data)
                    log.info(f"WAL replay: store_facts already present (user={user_id}), "
                             f"mark complete: {text[:40]}")
                    continue
                stored = _store_extracted_facts(text, source=source, user_id=user_id,
                                                is_replay=True)
                wal_engine.mark_complete(op, data)
                stats["replayed"] += 1
                log.info(f"WAL replay: replayed store_facts (user={user_id}) "
                         f"-> {len(stored)} facts: {text[:40]}")
            else:
                log.warning(f"WAL replay: unknown op '{op}', skipped (audit only)")
                stats["skipped"] += 1
        except Exception as e:
            stats["failed"] += 1
            # P2.5: 重试与死信熔断，避免毒记录反复重试
            # 健壮性：脏数据（非数值）不应导致 retry_count 未定义
            try:
                retry_count = int(data.get("retry_count") or 0) + 1
            except (TypeError, ValueError):
                retry_count = 1
            data["retry_count"] = retry_count
            if retry_count >= 3:
                log.error(
                    f"WAL replay: poisoning entry exceeded 3 retries, moving to dead_letter: "
                    f"{data} :: {e}"
                )
                # 销账 key 须与原始 append 一致：剔除原地注入的 retry_count（日志/告警中仍保留）
                original_data = {k: v for k, v in data.items() if k != "retry_count"}
                try:
                    wal_engine.mark_complete(op, original_data)
                except Exception as mark_err:
                    log.error(f"WAL replay: dead_letter mark_complete failed: {mark_err}")
            else:
                # 尚未熔断：retry_count 仅存内存，重启后会清零，记录清晰告警便于运维察觉
                log.warning(
                    f"WAL replay: op={op} failed (retry={retry_count}/3, counter resets on restart), "
                    f"payload={json.dumps(data, ensure_ascii=False)[:120]}: {e}"
                )

    log.info(
        f"WAL replay done: replayed={stats['replayed']}, "
        f"already_present={stats['already_present']}, "
        f"failed={stats['failed']}, skipped={stats['skipped']}"
    )
    return stats

# D1: 启动时执行 WAL 重放（须在 recall/extractor/_store_extracted_facts 就绪之后）
#     默认完整重放（幂等）；设环境变量 BAIZE_WAL_REPLAY=0 可显式降级为仅审计。
pending = wal.replay()
if pending:
    if os.environ.get("BAIZE_WAL_REPLAY", "1") != "1":
        log.warning(
            f"WAL 重放已禁用：pending {len(pending)} 条将被忽略（仅审计）。"
            f"如需恢复完整重放，请移除 BAIZE_WAL_REPLAY=0；"
            f"或调用 /api/cleanup 轮转 WAL 以清理历史 pending。"
        )
    else:
        log.info(f"WAL: {len(pending)} pending operations to replay")
        _replay_wal_pending(wal, pending)

# ===== FastAPI app =====
app = FastAPI(title="白泽 (Bai Ze)", version="1.5.0")

# P2a: 本地可视化页浏览器直连需 CORS（本地服务，allow all）
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic models ---
class AddRequest(BaseModel):
    messages: str  # JSON string of messages array
    user_id: str = "default"
    async_mode: bool = False
    metadata: dict = Field(default_factory=dict)

class SearchRequest(BaseModel):
    query: str
    user_id: str = "default"
    limit: int = 5
    # E3: 显式检索意图旁路——插件 baize_search 工具调用传 True 时跳过门控
    skip_gate: bool = False

# --- Endpoints ---
@app.get("/health")
def health():
    probes = {"db": os.path.exists(DB_PATH)}
    probes["vss"] = recall is not None

    # Probe embedding API connectivity (cached to avoid excessive API calls
    # on frequent health checks; re-probes at most once per _EMBED_PROBE_TTL seconds)
    now = time.time()
    if now - _embed_probe_cache["ts"] < _EMBED_PROBE_TTL:
        embedding_ok = _embed_probe_cache["ok"]
    elif embed_key:
        try:
            data = json.dumps({"model": "BAAI/bge-m3", "input": ["test"]}).encode()
            req = urllib.request.Request(
                "https://api.siliconflow.cn/v1/embeddings",
                data=data,
                headers={
                    "Authorization": f"Bearer {embed_key}",
                    "Content-Type": "application/json",
                },
            )
            urllib.request.urlopen(req, timeout=5)
            embedding_ok = True
        except Exception:
            embedding_ok = False
        _embed_probe_cache["ts"] = now
        _embed_probe_cache["ok"] = embedding_ok
    else:
        embedding_ok = False
    probes["embedding_api"] = embedding_ok

    # Rerank API: check key configured (don't call, avoid token consumption)
    probes["rerank_api"] = bool(reranker.api_key)

    # LLM API: check key configured (don't call)
    probes["llm_api"] = bool(llm_key)

    degraded = [k for k, v in probes.items() if not v]
    return {
        "status": "ok",
        "service": "白泽 (Bai Ze)",
        "version": "1.5.0-baize",
        "modules": {
            "gate": True,
            "fastpath": True,
            "coalesce": True,
            "decay": True,
            "hybrid_recall": recall is not None,
            "llm_extract": extractor is not None,
        },
        "probes": probes,
        "degraded": degraded,
    }

@app.get("/api/memory/health")
def memory_health():
    with get_db() as conn:
        cur = conn.cursor()
        # Lane distribution
        cur.execute("SELECT lane, COUNT(*) FROM memories GROUP BY lane")
        lane_dist = dict(cur.fetchall())
        # State distribution
        try:
            cur.execute("SELECT state, COUNT(*) FROM memory_states GROUP BY state")
            state_dist = dict(cur.fetchall())
        except:
            state_dist = {"active": sum(lane_dist.values())}
        # 7-day growth
        cur.execute("SELECT COUNT(*) FROM memories WHERE created_at > datetime('now','-7 days')")
        recent = cur.fetchone()[0]
        # Evolution relationships
        try:
            cur.execute("SELECT relation, COUNT(*) FROM knowledge_evolution GROUP BY relation")
            evo = dict(cur.fetchall())
        except:
            evo = {}
    return {
        "status": "ok",
        "version": "1.4.2-baize",
        "report": {
            "lane_distribution": lane_dist,
            "state_distribution": state_dist,
            "recent_7d_growth": recent,
            "evolution_relationships": evo,
        }
    }

@app.post("/add")
def add_memory(req: AddRequest):
    # Parse messages
    try:
        msgs = json.loads(req.messages)
        if isinstance(msgs, str):
            msgs = [{"role": "user", "content": msgs}]
    except json.JSONDecodeError:
        msgs = [{"role": "user", "content": req.messages}]

    # Combine message content + Reform: 提取发言角色用于 origin 打标
    texts = []
    has_user = False
    has_assistant = False
    for m in msgs:
        if isinstance(m, dict):
            texts.append(m.get("content", ""))
            r = m.get("role", "user")
            if r in ("user", "hermes_manual"):
                has_user = True
            elif r == "assistant":
                has_assistant = True
        elif isinstance(m, str):
            texts.append(m)
            has_user = True
    combined = "\n".join(t for t in texts if t.strip())

    if not combined.strip():
        return {"status": "empty", "memories": []}

    # Reform: 根据消息角色确定 origin：纯助手=agent-inferred，含用户=user
    if has_assistant and not has_user:
        msg_origin = "agent-inferred"
    else:
        msg_origin = "user"

    force_sync = req.metadata.get("force_sync", False)

    # Async mode
    if req.async_mode and not force_sync:
        job_id = str(uuid.uuid4())[:8]
        _purge_old_jobs()

        # Check coalesce first — use config mapping, fall back to default
        profile = req.metadata.get("source", "hermes")
        coalesce_profile = COALESCE_PROFILE_BY_SOURCE.get(profile, COALESCE_DEFAULT_PROFILE)

        result = coalesce.add_message(req.user_id, "session", combined, coalesce_profile)
        if result.get("action") == "coalesce_buffered":
            jobs[job_id] = {"status": "buffered", "created_at": time.time()}
            return {"action": "coalesce_buffered", "job_id": job_id}

        # Not coalesced, do async extraction
        jobs[job_id] = {"status": "processing", "created_at": time.time()}

        def do_extract():
            try:
                stored = _store_extracted_facts(combined, source=req.metadata.get("source", "hermes"),
                                                user_id=req.user_id, msg_origin=msg_origin)
                jobs[job_id] = {"status": "done", "memories": stored, "created_at": time.time()}
            except Exception as e:
                jobs[job_id] = {"status": "error", "error": str(e), "created_at": time.time()}

        threading.Thread(target=do_extract, daemon=True).start()
        return {"status": "accepted", "action": "async_queued", "job_id": job_id}

    # Sync mode
    stored = _store_extracted_facts(combined, source=req.metadata.get("source", "hermes"),
                                    user_id=req.user_id, msg_origin=msg_origin)
    return {"status": "ok", "memories": stored}


@app.post("/api/ingest")
def ingest_memories(req: AddRequest):
    """压缩归档直写端点（2026-08-07，压缩桥 L2）。

    与 /add 不同：不走 coalesce/LLM 提取，直接落库（快、零额外模型成本）。
    用于 on_pre_compress 钩子把将被压缩丢弃的工具输出/中间事实归档。
    items: [{content, lane?, source?}]——content 必填。
    完全重复内容（同 user 同 content）跳过，返回跳过数。
    """
    try:
        items = json.loads(req.messages)
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            items = []
    except (json.JSONDecodeError, TypeError):
        items = []

    inserted, skipped = 0, 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lane_map = {"identity", "preference", "procedural", "knowledge",
                "evidence", "lesson", "rule", "emotion", "general"}
    src = (req.metadata or {}).get("source", "compression")

    new_vector_tasks = []
    with get_db() as conn:
        cur = conn.cursor()
        for it in items:
            content = str(it.get("content", "")).strip() if isinstance(it, dict) else str(it).strip()
            if not content or len(content) < 10:
                continue
            # 简单去重：同 user 同 content 已有则跳过
            dup = cur.execute(
                "SELECT id FROM memories WHERE user_id=? AND content=? LIMIT 1",
                (req.user_id, content),
            ).fetchone()
            if dup:
                skipped += 1
                continue
            lane = it.get("lane", "general") if isinstance(it, dict) else "general"
            if lane not in lane_map:
                lane = "general"
            cur.execute(
                "INSERT INTO memories (user_id, content, lane, category, source, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (req.user_id, content, lane, lane, src, now),
            )
            mem_id = cur.lastrowid
            new_vector_tasks.append((mem_id, content))
            inserted += 1

    # 向量补写：在数据库事务之外执行，绝不阻塞主响应
    if recall and new_vector_tasks:
        for mem_id, content in new_vector_tasks:
            try:
                _store_vector(mem_id, content)
            except Exception as e:
                log.warning(f"ingest vector store failed for mem {mem_id}: {e}")

    return {"status": "ok", "inserted": inserted, "skipped": skipped, "source": src}

@app.get("/add/job/{job_id}")
def get_job_status(job_id: str):
    _purge_old_jobs()
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    return jobs[job_id]

@app.post("/search")
def search_memory(req: SearchRequest):
    # E3: skip_gate 时直接放行（显式检索意图）；否则走门控防自动注入浪费
    if req.skip_gate:
        gated = True
    else:
        gated = gate.needs_memory(req.query)
    if not gated:
        return {"results": [], "gated": False}

    results = []
    if recall:
        results = recall.search(req.query, user_id=req.user_id, limit=req.limit)
    else:
        # FTS-only fallback
        try:
            with get_db() as conn:
                cur = conn.cursor()
                cur.execute(
                    """SELECT m.id, m.content, m.category, m.lane, m.importance,
                              m.access_count, m.confirm_count, m.created_at
                       FROM memories_fts f
                       JOIN memories m ON f.rowid = m.id
                       WHERE memories_fts MATCH ? AND m.user_id = ?
                         AND m.id NOT IN (SELECT memory_id FROM memory_states
                                          WHERE state = 'superseded')
                       ORDER BY rank LIMIT ?""",
                    (req.query, req.user_id, req.limit)
                )
                for row in cur.fetchall():
                    created = datetime.fromisoformat(row["created_at"]).timestamp()
                    score = decay.get_score(row["lane"], created,
                                             access_count=row["access_count"],
                                             importance=row["importance"],
                                             confirm_count=row["confirm_count"])
                    if score > 0.05:
                        results.append({
                            "id": row["id"], "content": row["content"],
                            "category": row["category"], "lane": row["lane"],
                            "importance": row["importance"],
                            "created_at": row["created_at"],
                            "relevance": None,  # C7: FTS-only 降级路径无直接相关度
                            "score": round(score, 3),
                        })
                        cur.execute("UPDATE memories SET access_count = access_count + 1 WHERE id = ?",
                                    (row["id"],))
        except Exception as e:
            log.warning(f"FTS search failed: {e}")

    # F1: 主路径命中后累计 access_count（decay 的 access_boost 依赖它），
    #     高频记忆 importance 惰性微升（同一事务内读回 + 更新）
    if results and recall:
        try:
            ids = [r["id"] for r in results]
            with get_db() as conn:
                cur = conn.cursor()
                for rid in ids:
                    row = cur.execute(
                        "SELECT importance, access_count FROM memories WHERE id=?", (rid,)
                    ).fetchone()
                    if row:
                        new_imp = decay.evolve_importance(row[0], row[1] + 1)
                        if new_imp != row[0]:
                            cur.execute(
                                "UPDATE memories SET importance=?, access_count=access_count+1 WHERE id=?",
                                (new_imp, rid),
                            )
                        else:
                            cur.execute(
                                "UPDATE memories SET access_count=access_count+1 WHERE id=?", (rid,)
                            )
                conn.commit()
        except Exception as e:
            log.warning(f"access_count update failed: {e}")

    # Cross-Encoder rerank for precision boost
    should_rerank = True
    if results and len(results) > 1:
        top1_score = results[0].get("score", 0)
        top2_score = results[1].get("score", 0)
        # 点火直达（Ignition）：基于真实分布校准
        # 当 Top-1 混合得分 >= 0.45 且比第二名领先 >= 0.12 时，视为绝对高置信度保送，跳过外部 Rerank
        if top1_score >= 0.45 and (top1_score - top2_score) >= 0.12:
            should_rerank = False

    if results and len(results) > 1 and should_rerank:
        results = reranker.rerank(req.query, results, top_k=req.limit)

    return {"results": results, "gated": gated}


@app.post("/search_trace")
def search_memory_trace(req: SearchRequest):
    """P0: 追忆漏斗诊断端点，返回检索五阶段详情及耗时（毫秒）。"""
    if req.skip_gate:
        gated = True
    else:
        gated = gate.needs_memory(req.query)
    if not gated:
        return {"results": [], "gated": False, "trace": {"gate": False, "reason": "gated by memory_gate"}}

    results = []
    trace = {"gate": True}

    if recall:
        recall_out = recall.search(req.query, user_id=req.user_id, limit=req.limit, return_trace=True)
        results = recall_out.get("results", [])
        trace.update(recall_out.get("trace", {}))
    else:
        trace["fallback"] = "FTS-only"

    # Cross-Encoder rerank for precision boost
    should_rerank = True
    if results and len(results) > 1:
        top1_score = results[0].get("score", 0)
        top2_score = results[1].get("score", 0)
        # 点火直达（Ignition）：基于真实分布校准
        # 当 Top-1 混合得分 >= 0.45 且比第二名领先 >= 0.12 时，视为绝对高置信度保送，跳过外部 Rerank
        if top1_score >= 0.45 and (top1_score - top2_score) >= 0.12:
            should_rerank = False

    if results and len(results) > 1 and should_rerank:
        import time
        t_rr = time.perf_counter()
        pre_scores = [{"id": r.get("id"), "score": r.get("score")} for r in results]
        results = reranker.rerank(req.query, results, top_k=req.limit)
        trace["timings_ms"]["rerank"] = round((time.perf_counter() - t_rr) * 1000, 2)
        trace["stages"]["rerank_pre_scores"] = pre_scores
        trace["stages"]["rerank_post_scores"] = [{"id": r.get("id"), "score": r.get("score")} for r in results]

    return {"results": results, "gated": gated, "trace": trace}


@app.get("/api/rerank/status")
def rerank_status():
    """Get reranker status."""
    return {
        "model": reranker.model,
        "api_url": reranker.api_url,
        "has_key": bool(reranker.api_key),
    }


@app.get("/add/coalesce")
def coalesce_status():
    return {"buffers": coalesce.get_buffered_count()}

@app.get("/add/coalesce/stats")
def coalesce_stats():
    return coalesce.get_stats()

@app.post("/add/coalesce/flush")
def coalesce_flush(force: bool = False):
    if force:
        flushed = coalesce.check_idle_flush()
        return {"flushed": len(flushed), "results": flushed}
    return {"message": "Pass ?force=true to flush"}

# --- Facts (structured) ---
@app.post("/facts/add")
def add_fact(category: str, content: str, source: str = "manual",
             user_id: str = "default"):
    lane = decay.classify_lane(content, category)
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO memories (user_id, category, content, lane, importance, source)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, category, content, lane,
             0.9 if lane == "identity" else 0.7, source)
        )
        mem_id = cur.lastrowid
    return {"id": mem_id, "content": content, "lane": lane}

@app.get("/facts/list")
def list_facts(category: Optional[str] = None, user_id: str = "default",
               limit: int = 50, offset: int = 0):
    with get_db() as conn:
        cur = conn.cursor()
        if category:
            cur.execute(
                "SELECT * FROM memories WHERE user_id = ? AND category = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (user_id, category, limit, offset)
            )
        else:
            cur.execute(
                "SELECT * FROM memories WHERE user_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (user_id, limit, offset)
            )
        return {"facts": [dict(row) for row in cur.fetchall()]}

@app.get("/api/evolution/records")
def evolution_records(user_id: str = "default", limit: int = 50):
    """知识演化记录（只读）：source/target 记忆内容 + 关系 + 置信度。"""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT e.id, e.source_id, e.target_id, e.relation, e.confidence,
                      e.reason, e.created_at,
                      ms.content AS source_content, ms.lane AS source_lane,
                      mt.content AS target_content, mt.lane AS target_lane
               FROM knowledge_evolution e
               LEFT JOIN memories ms ON ms.id = e.source_id
               LEFT JOIN memories mt ON mt.id = e.target_id
               WHERE ms.user_id = ? OR mt.user_id = ?
               ORDER BY e.id DESC LIMIT ?""",
            (user_id, user_id, limit)
        )
        return {"records": [dict(row) for row in cur.fetchall()]}


@app.get("/api/graph/subgraph")
def graph_subgraph(q: str = "", lane: str = "", top_n: int = 120,
                   max_edges: int = 240, hops: int = 1, user_id: str = "default"):
    """知识星图子图查询（只读，2026-08-10 知识星图 T1）。

    节点 = 记忆，边 = knowledge_evolution 演化关系（enriches/replaces/confirms）。
    无 q：按 importance×degree 取高分节点；有 q：FTS/LIKE 搜种子后
    沿演化边 BFS 扩展 1-2 跳。节点/边硬截断防蜘蛛网，meta.truncated 标记。
    """
    try:
        top_n = max(10, min(int(top_n), 300))
        max_edges = max(20, min(int(max_edges), 800))
        hops = 1 if int(hops) < 1 else (2 if int(hops) > 2 else int(hops))
        with get_db() as conn:
            cur = conn.cursor()
            # 1. 种子节点
            if q and q.strip():
                try:
                    rows = cur.execute(
                        """SELECT f.rowid FROM memories_fts f
                           JOIN memories m ON f.rowid = m.id
                           WHERE memories_fts MATCH ? AND m.user_id = ? LIMIT 15""",
                        (q.strip(), user_id)
                    ).fetchall()
                    seed_ids = [r["rowid"] for r in rows]
                except Exception:
                    seed_ids = []
                if not seed_ids:
                    rows = cur.execute(
                        "SELECT id FROM memories WHERE user_id=? AND content LIKE ? LIMIT 15",
                        (user_id, f"%{q.strip()}%")
                    ).fetchall()
                    seed_ids = [r["id"] for r in rows]
            else:
                rows = cur.execute("""
                    SELECT m.id FROM memories m
                    LEFT JOIN (
                        SELECT id, COUNT(*) AS deg FROM (
                            SELECT source_id AS id FROM knowledge_evolution
                            UNION ALL SELECT target_id AS id FROM knowledge_evolution
                        ) GROUP BY id
                    ) d ON d.id = m.id
                    WHERE m.user_id = ?
                    ORDER BY m.importance * (COALESCE(d.deg, 0) + 1) DESC LIMIT ?""",
                    (user_id, top_n)
                ).fetchall()
                seed_ids = [r["id"] for r in rows]
            if not seed_ids:
                return {"nodes": [], "edges": [],
                        "meta": {"node_count": 0, "edge_count": 0, "truncated": False}}

            # 2. BFS 扩展（hops>0 时；内部已过滤 superseded + user 归属）
            related = {}
            if hops > 0:
                try:
                    related = evolution.get_related(seed_ids, hops=hops,
                                                    max_per_hop=20, user_id=user_id)
                except Exception as e:
                    log.warning(f"graph BFS failed: {e}")
            node_ids = set(seed_ids) | set(related.keys())

            # 3. lane 过滤（可选）
            if lane and node_ids:
                ph = ",".join("?" * len(node_ids))
                keep = {r["id"] for r in cur.execute(
                    f"SELECT id FROM memories WHERE id IN ({ph}) AND lane = ?",
                    (*node_ids, lane)
                ).fetchall()}
                node_ids = keep

            # 4. 取边（两端都在节点集内，置信度降序截断）
            if node_ids:
                ph = ",".join("?" * len(node_ids))
                edges = cur.execute(
                    f"""SELECT source_id, target_id, relation, confidence
                        FROM knowledge_evolution
                        WHERE source_id IN ({ph}) AND target_id IN ({ph})
                        ORDER BY confidence DESC, id DESC LIMIT ?""",
                    (*node_ids, *node_ids, max_edges)
                ).fetchall()
            else:
                edges = []

            # 5. 组装节点 + degree
            if node_ids:
                ph = ",".join("?" * len(node_ids))
                nodes_raw = cur.execute(
                    f"SELECT id, content, lane, importance FROM memories WHERE id IN ({ph})",
                    (*node_ids,)
                ).fetchall()
            else:
                nodes_raw = []
            nodes = [{
                "id": r["id"], "label": (r["content"] or "")[:40],
                "lane": r["lane"], "importance": round(float(r["importance"] or 0), 2),
                "degree": 0,
            } for r in nodes_raw]
            if node_ids:
                ph = ",".join("?" * len(node_ids))
                deg_rows = cur.execute(
                    f"""SELECT id, COUNT(*) AS deg FROM (
                            SELECT source_id AS id FROM knowledge_evolution WHERE source_id IN ({ph})
                            UNION ALL SELECT target_id AS id FROM knowledge_evolution WHERE target_id IN ({ph})
                        ) GROUP BY id""",
                    (*node_ids, *node_ids)
                ).fetchall()
                deg_map = {r["id"]: r["deg"] for r in deg_rows}
                for n in nodes:
                    n["degree"] = deg_map.get(n["id"], 0)

            edge_list = [{
                "source": e["source_id"], "target": e["target_id"],
                "relation": e["relation"], "confidence": round(float(e["confidence"] or 0), 2),
            } for e in edges]

            return {"nodes": nodes, "edges": edge_list,
                    "meta": {"node_count": len(nodes), "edge_count": len(edge_list),
                             "truncated": len(edges) >= max_edges}}
    except HTTPException:
        raise
    except Exception as e:
        log.exception("graph subgraph failed")
        raise HTTPException(500, f"graph subgraph failed: {e}")

@app.delete("/facts/{fact_id}")
def delete_fact(fact_id: int):
    with get_db() as conn:
        cur = conn.cursor()
        # memory_vec 是 vec0 虚拟表，需加载扩展才能 DELETE（A2: 此前静默失败）
        if HAS_SQLITE_VEC:
            try:
                conn.enable_load_extension(True)
                sqlite_vec.load(conn)
            except Exception as e:
                log.warning(f"sqlite_vec load failed in delete_fact: {e}")
        # Clean up orphan vector first (float)
        try:
            cur.execute("SELECT rowid FROM memory_vec WHERE rowid = ?", (fact_id,))
            if cur.fetchone():
                cur.execute("DELETE FROM memory_vec WHERE rowid = ?", (fact_id,))
                log.info(f"Cleaned up memory_vec vector for fact {fact_id}")
        except Exception as e:
            log.warning(f"memory_vec cleanup skipped (table may not exist): {e}")
        # A2: 同步清理 int8 表（普通表，无需扩展）
        try:
            cur.execute("DELETE FROM memory_vec_i8 WHERE mem_id = ?", (fact_id,))
            if cur.rowcount:
                log.info(f"Cleaned up memory_vec_i8 vector for fact {fact_id}")
        except Exception as e:
            log.warning(f"memory_vec_i8 cleanup skipped (table may not exist): {e}")
        # 清理演化关系表中涉及该记忆的边
        cur.execute("DELETE FROM knowledge_evolution WHERE source_id = ? OR target_id = ?", (fact_id, fact_id))
        # 清理状态表中该记忆的状态记录
        cur.execute("DELETE FROM memory_states WHERE memory_id = ?", (fact_id,))
        # 清理可能的合并建议
        cur.execute("DELETE FROM merge_suggestions WHERE keep_id = ? OR other_id = ?", (fact_id, fact_id))
        # Then delete the memory record
        cur.execute("DELETE FROM memories WHERE id = ?", (fact_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "Fact not found")
    return {"deleted": fact_id}

# --- Memory trimming (waterline control) ---
def _trim_memory():
    """Actively return unused heap memory to the OS.

    CPython's small-object allocator (pymalloc) keeps freed arenas cached and
    never returns them, so long-running processes accumulate a high memory
    watermark. gc.collect() + platform heap compaction returns memory.
    Linux 化：Windows 用 ucrtbase._heapmin，Linux 用 glibc malloc_trim。
    """
    try:
        gc.collect()
        if sys.platform == "win32":
            ctypes.CDLL("ucrtbase.dll")._heapmin()
        else:
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        log.info("Memory trim: gc + heap compaction done")
    except Exception as e:
        log.warning(f"Memory trim failed: {e}")

# --- Background tasks ---
def periodic_flush():
    """Periodically flush idle coalesce buffers."""
    # Poll at half the fastest idle_sec to catch thresholds promptly
    min_idle = min(p["idle_sec"] for p in PROFILES.values())
    poll_interval = max(min_idle / 2, 0.5)
    last_trim = 0.0
    TRIM_INTERVAL = 1800.0  # 30 分钟
    WAL_CLEANUP_INTERVAL = 24 * 3600.0  # 每天一次 WAL 清理
    last_wal_cleanup = time.time()
    # AutoDream 调度：日更增量（days=1）+ 周全量（days=7）
    AUTODREAM_DAILY_INTERVAL = 24 * 3600.0
    AUTODREAM_WEEKLY_INTERVAL = 7 * 24 * 3600.0
    last_autodream_daily = time.time()
    last_autodream_weekly = time.time()
    while True:
        time.sleep(poll_interval)
        now = time.time()
        if now - last_trim >= TRIM_INTERVAL:
            _trim_memory()
            last_trim = now
        if now - last_wal_cleanup >= WAL_CLEANUP_INTERVAL:
            try:
                removed = wal.cleanup()
                log.info(f"Periodic WAL cleanup: removed={removed}")
            except Exception as e:
                log.warning(f"Periodic WAL cleanup failed: {e}", exc_info=True)
            last_wal_cleanup = now
        # AutoDream 日更/周更调度
        if now - last_autodream_daily >= AUTODREAM_DAILY_INTERVAL:
            try:
                log.info("AutoDream daily incremental triggered (days=1)")
                result = auto_dream.run_distillation(days=1, user_id="default")
                _rebuild_vectors(result)
                log.info(f"AutoDream daily done: {result}")
            except Exception as e:
                log.warning(f"AutoDream daily failed: {e}", exc_info=True)
            last_autodream_daily = now
        if now - last_autodream_weekly >= AUTODREAM_WEEKLY_INTERVAL:
            try:
                log.info("AutoDream weekly full triggered (days=7)")
                result = auto_dream.run_distillation(days=7, user_id="default")
                _rebuild_vectors(result)
                log.info(f"AutoDream weekly done: {result}")
            except Exception as e:
                log.warning(f"AutoDream weekly failed: {e}", exc_info=True)
            last_autodream_weekly = now
        try:
            flushed = coalesce.check_idle_flush()
            if flushed:
                counts = [r["count"] for r in flushed if r.get("action") == "wave_flushed"]
                if counts:
                    log.info("periodic_flush: %d buffers flushed (%s)", len(flushed), counts)
        except Exception as e:
            log.warning(f"Periodic flush error: {e}", exc_info=True)

# Start background flush thread
flush_thread = threading.Thread(target=periodic_flush, daemon=True)
flush_thread.start()

# --- CoreMemory ---
@app.get("/api/core-memory")
def get_core_memory(user_id: str = "default"):
    """Get all core memory blocks."""
    return {"blocks": core_memory.get_all(user_id)}

@app.get("/api/core-memory/{block_name}")
def get_core_memory_block(block_name: str, user_id: str = "default"):
    """Get a single core memory block."""
    result = core_memory.get(block_name, user_id)
    if result is None:
        raise HTTPException(404, f"Block '{block_name}' not found")
    return result

class CoreMemoryUpdate(BaseModel):
    content: str

@app.put("/api/core-memory/{block_name}")
def update_core_memory(block_name: str, req: CoreMemoryUpdate, user_id: str = "default"):
    """Update a core memory block."""
    if not core_memory.update(block_name, req.content, user_id):
        raise HTTPException(400, f"Invalid block name: {block_name}")
    return {"status": "ok", "block_name": block_name}

# --- AutoDream ---
@app.post("/api/auto-dream")
def run_auto_dream(days: int = 7, async_mode: bool = True, user_id: str = "default"):
    """Trigger memory distillation.

    Runs async by default (distillation can take ~30s). Pass async_mode=false
    for synchronous execution. Async results are polled via /add/job/{job_id}.
    D3: user_id 限定蒸馏范围（只处理该用户的记忆）。
    """
    if not async_mode:
        # Synchronous mode (backward compatible)
        # B4: 蒸馏合并后会更新 keep_id 的 content，同步重建其向量
        # C6: 异常 → 500，不泄露原始异常串
        try:
            result = auto_dream.run_distillation(days=days, user_id=user_id)
            _rebuild_vectors(result)
            return result
        except Exception as e:
            log.error(f"Auto-dream failed: {e}")
            raise HTTPException(500, "distillation failed")

    job_id = str(uuid.uuid4())[:8]
    _purge_old_jobs()
    jobs[job_id] = {"status": "processing", "created_at": time.time()}

    def do_distill():
        try:
            result = auto_dream.run_distillation(days=days, user_id=user_id)
            # B4: 合并后重建 keep_id 向量（float+i8 双写）
            _rebuild_vectors(result)
            jobs[job_id] = {"status": "done", "result": result, "created_at": time.time()}
        except Exception as e:
            jobs[job_id] = {"status": "error", "error": str(e), "created_at": time.time()}

    threading.Thread(target=do_distill, daemon=True).start()
    return {"status": "accepted", "action": "async_queued", "job_id": job_id}

@app.post("/api/consolidate/session")
def consolidate_session(minutes=30, dup_threshold=0.85,
                        cand_threshold=0.70, user_id: str = "default"):
    """P1-3: 会话级快速合并 — 轻量 Jaccard 去重最近 N 分钟写入（无 LLM，毫秒级）。

    与 /api/auto-dream（7 天级深度蒸馏）互补，适合会话结束后立即收敛。
    D3: user_id 限定合并范围。
    C4: 非法类型（非数值）→ 400；越界值由 run_session_consolidation 钳制。
    C6: 异常 → 500，不向外泄露原始异常串。
    """
    try:
        minutes = int(minutes)
        dup_threshold = float(dup_threshold)
        cand_threshold = float(cand_threshold)
    except (TypeError, ValueError):
        raise HTTPException(
            400,
            "invalid consolidation parameters: "
            "minutes/dup_threshold/cand_threshold must be numeric",
        )
    try:
        return auto_dream.run_session_consolidation(
            minutes=minutes,
            dup_threshold=dup_threshold,
            cand_threshold=cand_threshold,
            user_id=user_id,
        )
    except Exception as e:
        log.error(f"Session consolidation failed: {e}")
        raise HTTPException(500, "consolidation failed")

@app.post("/api/cleanup")
def cleanup_memories(threshold: float = 0.1, user_id: str = "default"):
    """P0-2: 归档衰减分数低于阈值的记忆 + 清理孤儿向量 + 轮转 WAL。

    C6: 异常 → 500，不泄露原始异常串。
    """
    try:
        archived = 0
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, lane, importance, access_count, created_at FROM memories WHERE user_id = ?",
                (user_id,)
            )
            for row in cur.fetchall():
                created_ts = datetime.fromisoformat(row["created_at"]).timestamp()
                if decay.should_archive(row["lane"], created_ts, threshold=threshold,
                                        importance=row["importance"],
                                        access_count=row["access_count"]):
                    # identity/preference 零衰减 get_score >= 0.8 天然不会触发，双保险
                    cur.execute(
                        "INSERT OR REPLACE INTO memory_states (memory_id, state, reason, source, updated_at) "
                        "VALUES (?, 'superseded', ?, 'cleanup', datetime('now','localtime'))",
                        (row["id"], f"decay below {threshold}")
                    )
                    archived += 1
            # 清理 memory_vec 中已 superseded 记忆的孤儿向量（A2: 同步清 float + int8）
            # memory_vec 是 vec0 虚拟表，需加载扩展才能 DELETE（此前静默失败）
            if HAS_SQLITE_VEC:
                try:
                    conn.enable_load_extension(True)
                    sqlite_vec.load(conn)
                except Exception as e:
                    log.warning(f"sqlite_vec load failed in cleanup: {e}")
            try:
                cur.execute(
                    """DELETE FROM memory_vec WHERE rowid IN
                       (SELECT s.memory_id FROM memory_states s
                        JOIN memories m ON m.id = s.memory_id
                        WHERE s.state = 'superseded')"""
                )
            except Exception as e:
                log.warning(f"Vec cleanup skipped: {e}")
            try:
                cur.execute(
                    """DELETE FROM memory_vec_i8 WHERE mem_id IN
                       (SELECT s.memory_id FROM memory_states s
                        JOIN memories m ON m.id = s.memory_id
                        WHERE s.state = 'superseded')"""
                )
            except Exception as e:
                log.warning(f"Vec_i8 cleanup skipped: {e}")
        removed = wal.cleanup()  # WAL 轮转（retention 7 天）
        log.info(f"Cleanup done: archived={archived}, wal_removed={removed}")
        return {"status": "ok", "archived": archived, "wal_removed": removed}
    except Exception as e:
        log.error(f"Cleanup failed: {e}")
        raise HTTPException(500, "cleanup failed")

# ===== Main =====

if __name__ == "__main__":
    log.info(f"Starting 白泽 (Bai Ze) on port {PORT}")
    log.info(f"  DB: {DB_PATH}")
    log.info(f"  sqlite-vec: {'enabled' if recall else 'disabled'}")
    log.info(f"  LLM: {LLM_API_URL} ({LLM_MODEL})")
    log.info(f"  Embed key: {'set' if embed_key else 'missing'}")
    log.info(f"  LLM key: {'set' if llm_key else 'missing'}")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
