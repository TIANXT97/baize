#!/usr/bin/env python3
"""2026-09-15 白泽烂账清算（配合事前备份 facts.db.bak-preaudit-20260915）
① 22条'...'空壳  ② 281条字面重复(留最早一条)  ③ 7条断头演化链
④ 4条测试残渣(精确ID)  ⑤ id=51562 畸形户矫正(不删)
全程先导出存档，单事务，验账不符即回滚。"""
import sqlite3, json, os, sys, time

DB = "/root/.hermes/baize/data/facts.db"
ARCHIVE = "/root/.hermes/baize/backups/audit_salvage_20260915.jsonl"

c = sqlite3.connect(DB, timeout=30.0)
c.execute("PRAGMA busy_timeout = 30000")
cur = c.cursor()
t0 = time.time()

# ── 集合构建（全部精确圈定，宁漏勿冤）──
shells = [r[0] for r in cur.execute(
    "SELECT id FROM memories WHERE trim(content)='...'").fetchall()]
# 字面重复：每组留 id 最小（最早）那条，删其余
dupes = []
for r in cur.execute("""SELECT content, group_concat(id) FROM memories
    GROUP BY content HAVING count(*)>1"""):
    ids = sorted(int(x) for x in r[1].split(","))
    dupes.extend(ids[1:])
test_ids = [46, 50210, 49167, 4798]   # test / compression_test / 测试向量重建 / e2e-test
# 安全阀：残渣 30 号(位置)与 88 号(Tavily共用key)、51562、53807 是真事，不删
kill = sorted(set(shells) | set(dupes) | set(test_ids))
if not kill:
    print("无目标，退出"); sys.exit(0)
print(f"[圈定] 空壳{len(shells)} 重复{len(dupes)} 测试{len(test_ids)} → 去重后共删 {len(kill)} 条")
if len(kill) > 400:
    print(f"!! 圈定 {len(kill)} 超上限400，中止"); sys.exit(1)

ph = ",".join("?" * len(kill))
total_before = cur.execute("SELECT count(*) FROM memories").fetchone()[0]
fts_before = cur.execute("SELECT count(*) FROM memories_fts").fetchone()[0]

# ── 存档（被删行 + 待矫正行的原值）──
os.makedirs(os.path.dirname(ARCHIVE), exist_ok=True)
with open(ARCHIVE, "w", encoding="utf-8") as f:
    for r in cur.execute(
        f"SELECT id,user_id,category,lane,importance,content,created_at,source "
        f"FROM memories WHERE id IN ({ph}) ORDER BY id", kill):
        f.write(json.dumps({"action": "delete", "row": {
            "id": r[0], "user_id": r[1], "category": r[2], "lane": r[3],
            "importance": r[4], "content": r[5], "created_at": r[6], "source": r[7],
        }}, ensure_ascii=False) + "\n")
    r = cur.execute("SELECT id,source,importance,lane,user_id,created_at "
                    "FROM memories WHERE id=51562").fetchone()
    f.write(json.dumps({"action": "fix", "row": {
        "id": 51562, "old": {"source": r[1], "importance": r[2], "lane": r[3],
                             "user_id": r[4], "created_at": r[5]}
    }}, ensure_ascii=False) + "\n")
arch_n = sum(1 for _ in open(ARCHIVE, encoding="utf-8"))
print(f"[存档] {arch_n} 行 → {ARCHIVE}")

# ── 单事务清算 ──
try:
    cur.execute("BEGIN")
    # ③ 断头演化链：重建 join 判定，整七条
    ke = cur.execute("""DELETE FROM knowledge_evolution WHERE id IN (
        SELECT k.id FROM knowledge_evolution k
        LEFT JOIN memories a ON k.source_id=a.id
        LEFT JOIN memories b ON k.target_id=b.id
        WHERE a.id IS NULL OR b.id IS NULL)""").rowcount
    # 附属表先清（防止删主表后留新悬挂）
    ms = cur.execute(f"DELETE FROM memory_states WHERE memory_id IN ({ph})", kill).rowcount
    ke2 = cur.execute(f"""DELETE FROM knowledge_evolution WHERE source_id IN ({ph})
        OR target_id IN ({ph})""", kill + kill).rowcount
    msn = cur.execute(f"""DELETE FROM merge_suggestions WHERE keep_id IN ({ph})
        OR other_id IN ({ph})""", kill + kill).rowcount
    # ①②④ 主表
    mem = cur.execute(f"DELETE FROM memories WHERE id IN ({ph})", kill).rowcount
    # ⑤ 畸形户矫正（不删）：source→hermes_manual、importance→0.8、
    #   lane→general(非法'garden'归正，category 'project' 保留由 classify 兜 lane)、
    #   user_id→default、created_at 数字串→可读时间
    from datetime import datetime
    fixed_at = datetime.fromtimestamp(1789184206).strftime("%Y-%m-%d %H:%M:%S")
    fx = cur.execute("""UPDATE memories SET source='hermes_manual', importance=0.8,
        lane='knowledge', user_id='default', created_at=? WHERE id=51562""",
        (fixed_at,)).rowcount
    print(f"[开刀] 演化链断头={ke} states={ms} evo悬挂={ke2} merge={msn} "
          f"主表删={mem} 矫正={fx}")

    # ── 事务内验账 ──
    total_after = cur.execute("SELECT count(*) FROM memories").fetchone()[0]
    fts_after = cur.execute("SELECT count(*) FROM memories_fts").fetchone()[0]
    left_shell = cur.execute("SELECT count(*) FROM memories WHERE trim(content)='...'").fetchone()[0]
    left_dup = cur.execute("SELECT COALESCE(sum(n-1),0) FROM (SELECT count(*) n FROM memories GROUP BY content HAVING n>1)").fetchone()[0]
    left_ke = cur.execute("""SELECT count(*) FROM knowledge_evolution k
        LEFT JOIN memories a ON k.source_id=a.id LEFT JOIN memories b ON k.target_id=b.id
        WHERE a.id IS NULL OR b.id IS NULL""").fetchone()[0]
    ok51 = cur.execute("SELECT source,importance,lane,user_id FROM memories WHERE id=51562").fetchone()
    expect = total_before - len(kill)
    print(f"[验账] memories {total_after} (期望{expect}) | fts差={fts_before-fts_after} (期望{len(kill)})")
    print(f"      空壳残留={left_shell} 字面重复残留={left_dup} 断头链残留={left_ke}")
    print(f"      51562现状={ok51}")
    if total_after != expect or (fts_before - fts_after) != len(kill) \
       or left_shell or left_ke or ok51[0] != 'hermes_manual':
        raise RuntimeError("验账不符 → ROLLBACK")
    c.commit()
    print(f"[提交] ✅ 清算完成 {time.time()-t0:.1f}s，净删 {len(kill)} 条")
except Exception as e:
    c.rollback()
    print(f"[回滚] ❌ {e}")
    sys.exit(2)
finally:
    c.close()
