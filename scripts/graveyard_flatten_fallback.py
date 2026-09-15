#!/usr/bin/env python3
"""2026-09-15 平坟：清理 source='fallback' 的 883 条原文垃圾。
前置：已停 baize 服务、已做全库备份。本脚本负责 ③导出存档 ④四点清表。
安全阀：删除前后各跑一次对账，行数不符预期立即回滚（事务未提交前 abort）。"""
import sqlite3, json, os, sys, time

DB = "/root/.hermes/baize/data/facts.db"
ARCHIVE = "/root/.hermes/baize/backups/fallback_salvage_20260915.jsonl"

t0 = time.time()
conn = sqlite3.connect(DB, timeout=30.0)
conn.execute("PRAGMA busy_timeout = 30000")
cur = conn.cursor()

# ---- 清点目标 ----
ids = [r[0] for r in cur.execute(
    "SELECT id FROM memories WHERE source='fallback'").fetchall()]
n = len(ids)
print(f"[清点的] 目标 fallback 行数: {n}")
if n < 800 or n > 1000:
    print("!! 数量不在预期区间(800-1000)，中止，不做任何修改")
    sys.exit(1)

total_before = cur.execute("SELECT count(*) FROM memories").fetchone()[0]
fts_before = cur.execute("SELECT count(*) FROM memories_fts").fetchone()[0]
print(f"[对账] 删除前: memories={total_before}  memories_fts={fts_before}")

# ---- 导出存档（一条不落）----
os.makedirs(os.path.dirname(ARCHIVE), exist_ok=True)
with open(ARCHIVE, "w", encoding="utf-8") as f:
    for r in cur.execute(
        "SELECT id, user_id, category, lane, importance, content, created_at "
        "FROM memories WHERE source='fallback' ORDER BY id"):
        f.write(json.dumps({
            "id": r[0], "user_id": r[1], "category": r[2], "lane": r[3],
            "importance": r[4], "content": r[5], "created_at": r[6],
        }, ensure_ascii=False) + "\n")
arch_n = sum(1 for _ in open(ARCHIVE, encoding="utf-8"))
print(f"[存档] {arch_n} 条 → {ARCHIVE}")
if arch_n != n:
    print("!! 存档行数与目标不符，中止")
    sys.exit(1)

# ---- 开事务，四点清表 ----
ph = ",".join("?" * n)
try:
    cur.execute("BEGIN")
    ms = cur.execute(f"DELETE FROM memory_states WHERE memory_id IN ({ph})", ids).rowcount
    ke = cur.execute(
        f"DELETE FROM knowledge_evolution WHERE source_id IN ({ph}) OR target_id IN ({ph})",
        ids + ids).rowcount
    msn = cur.execute(
        f"DELETE FROM merge_suggestions WHERE keep_id IN ({ph}) OR other_id IN ({ph})",
        ids + ids).rowcount
    mem = cur.execute(f"DELETE FROM memories WHERE source='fallback' AND id IN ({ph})", ids).rowcount
    print(f"[清表] memory_states={ms} knowledge_evolution={ke} "
          f"merge_suggestions={msn} memories={mem}")

    # ---- 事务内验账 ----
    total_after = cur.execute("SELECT count(*) FROM memories").fetchone()[0]
    left_fb = cur.execute("SELECT count(*) FROM memories WHERE source='fallback'").fetchone()[0]
    fts_after = cur.execute("SELECT count(*) FROM memories_fts").fetchone()[0]
    expect = total_before - n
    print(f"[对账] 删除后: memories={total_after} (期望{expect}) "
          f"残留fallback={left_fb} fts={fts_after}")
    if total_after != expect or left_fb != 0:
        raise RuntimeError("对账不符 → ROLLBACK")
    # FTS 允许小偏差（触发器实时同步，理论上精确），大偏差也回滚
    if abs(fts_after - fts_before) not in (n,):
        print(f"!! FTS 差值 {fts_before - fts_after} != {n} → ROLLBACK")
        raise RuntimeError("FTS sync mismatch → ROLLBACK")

    conn.commit()
    print(f"[提交] ✅ 平坟完成，用时 {time.time()-t0:.1f}s")
except Exception as e:
    conn.rollback()
    print(f"[回滚] ❌ {e} —— 库未受损")
    sys.exit(2)
finally:
    conn.close()
