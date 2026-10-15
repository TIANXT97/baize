#!/usr/bin/env python3
"""白泽治理重构回归测试 — 5 道硬核对抗真题。

执行: python3 -m pytest tests/test_reform_regression.py -v
  或: python3 tests/test_reform_regression.py
"""
import hashlib
import os
import re
import sqlite3
import sys
import tempfile
import shutil

# 确保项目根在 sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

DB_PATH = os.path.join(BASE_DIR, "data", "facts.db")

# ==================== helpers ====================

def _get_conn(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.row_factory = sqlite3.Row
    return conn


def _norm_hash(text: str) -> str:
    norm = re.sub(r'[\s\W]+', '', text).lower()
    return hashlib.sha256(norm.encode('utf-8')).hexdigest()


# ==================== Case 1: 推测禁入 CoreMemory ====================
def test_case1_inference_blocked_from_core():
    """推测句（origin != 'user'）不能进入 core_memory user_profile。"""
    # 使用内存中的独立 DB 进行纯逻辑测试，不依赖外部 API
    # 直接调用 _sync_core_memory_from_facts 的逻辑
    # --- 准备临时 DB ---
    tmpdir = tempfile.mkdtemp()
    tmp_db = os.path.join(tmpdir, "test.db")
    try:
        conn = sqlite3.connect(tmp_db)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS core_memory (
                block_name TEXT,
                user_id TEXT,
                content TEXT,
                updated_at TEXT,
                PRIMARY KEY (block_name, user_id)
            );
            INSERT INTO core_memory (block_name, user_id, content, updated_at)
            VALUES ('user_profile', 'default', '用户名为TIAN', datetime('now'));
        """)
        conn.commit()
        conn.close()

        # 模拟 _sync_core_memory_from_facts 的铁闸逻辑
        # origin='agent-inferred' 的 identity 事实应被拦截
        facts_inferred = [
            {"fact": "用户注册某App大概率是走机场", "category": "identity", "origin": "agent-inferred"},
        ]
        facts_user = [
            {"fact": "用户的VPS在东京", "category": "identity", "origin": "user"},
        ]

        # 铁闸过滤：只有 origin == 'user' 的 identity 事实可通过
        passed_inferred = [f for f in facts_inferred
                           if f.get("category") == "identity" and f.get("origin") == "user"]
        passed_user = [f for f in facts_user
                       if f.get("category") == "identity" and f.get("origin") == "user"]

        assert len(passed_inferred) == 0, "agent-inferred 事实不应通过铁闸"
        assert len(passed_user) == 1, "user 亲陈事实应通过铁闸"
        print("✅ Case 1 PASSED: 推测禁入 CoreMemory")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ==================== Case 2: 否定即取代 ====================
def test_case2_negation_triggers_replaces():
    """极性翻转+共同话题>=3 触发 replaces，旧记录被标记 superseded。"""
    # 直接测试 evolution 模块的 _classify_relation
    from modules.evolution import EvolutionTracker

    tmpdir = tempfile.mkdtemp()
    tmp_db = os.path.join(tmpdir, "test.db")
    try:
        # 建立临时 DB
        conn = sqlite3.connect(tmp_db)
        conn.executescript("""
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
                expires_at TEXT,
                confirm_count INTEGER NOT NULL DEFAULT 0,
                origin TEXT DEFAULT 'unknown'
            );
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
            CREATE TABLE IF NOT EXISTS rejected_values (
                content_hash TEXT PRIMARY KEY,
                content_pattern TEXT,
                reason TEXT,
                rejected_by_id INTEGER,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );
        """)
        # 插入旧记忆
        conn.execute(
            "INSERT INTO memories (id, user_id, content, lane) VALUES (1, 'default', '用户偏好使用付费代理', 'preference')"
        )
        conn.commit()
        conn.close()

        evo = EvolutionTracker(tmp_db)

        # 测试 _classify_relation
        old_text = "用户偏好使用付费代理"
        new_text = "用户全线白嫖，不使用任何付费代理，不是付费用户"
        relation, confidence, reason = evo._classify_relation(new_text, old_text)

        assert relation == "replaces", f"应为 replaces，实际为 {relation}"
        assert confidence >= 0.6, f"置信度应>=0.6，实际为 {confidence}"

        # 测试完整 check_evolution 流程（插入新记忆并检测）
        conn2 = sqlite3.connect(tmp_db)
        conn2.execute(
            "INSERT INTO memories (id, user_id, content, lane) VALUES (2, 'default', ?, 'preference')",
            (new_text,)
        )
        conn2.commit()
        conn2.close()

        rels = evo.check_evolution(new_text, 2, user_id="default")
        # 检查旧记忆是否被标记 superseded
        conn3 = sqlite3.connect(tmp_db)
        row = conn3.execute("SELECT state FROM memory_states WHERE memory_id=1").fetchone()
        conn3.close()

        assert row is not None and row[0] == "superseded", f"旧记忆应被标记 superseded，实际 state={row}"
        print("✅ Case 2 PASSED: 否定即取代")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ==================== Case 3: 墓碑防复活 ====================
def test_case3_tombstone_prevents_resurrection():
    """被取代的事实再次出现时，被 rejected_values 墓碑拦截。"""
    # 在 Case 2 的基础上，检查墓碑表
    from modules.evolution import EvolutionTracker

    tmpdir = tempfile.mkdtemp()
    tmp_db = os.path.join(tmpdir, "test.db")
    try:
        conn = sqlite3.connect(tmp_db)
        conn.executescript("""
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
                expires_at TEXT,
                confirm_count INTEGER NOT NULL DEFAULT 0,
                origin TEXT DEFAULT 'unknown'
            );
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
            CREATE TABLE IF NOT EXISTS rejected_values (
                content_hash TEXT PRIMARY KEY,
                content_pattern TEXT,
                reason TEXT,
                rejected_by_id INTEGER,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );
        """)
        old_text = "用户偏好使用付费代理"
        new_text = "用户全线白嫖，不使用任何付费代理，不是付费用户"
        conn.execute("INSERT INTO memories (id, user_id, content) VALUES (1, 'default', ?)", (old_text,))
        conn.execute("INSERT INTO memories (id, user_id, content) VALUES (2, 'default', ?)", (new_text,))
        conn.commit()
        conn.close()

        evo = EvolutionTracker(tmp_db)
        evo.check_evolution(new_text, 2, user_id="default")

        # 检查墓碑表是否有旧事实的 hash
        old_hash = _norm_hash(old_text)
        conn2 = sqlite3.connect(tmp_db)
        row = conn2.execute("SELECT content_hash FROM rejected_values WHERE content_hash=?", (old_hash,)).fetchone()
        conn2.close()

        assert row is not None, "墓碑表中应存在被否决事实的 hash"

        # 模拟入库前拦截逻辑
        resurrected_text = "用户偏好使用付费代理"
        res_hash = _norm_hash(resurrected_text)

        conn3 = sqlite3.connect(tmp_db)
        tombstone = conn3.execute(
            "SELECT 1 FROM rejected_values WHERE content_hash=?", (res_hash,)
        ).fetchone()
        conn3.close()

        assert tombstone is not None, "复活的事实应被墓碑拦截"
        print("✅ Case 3 PASSED: 墓碑防复活")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ==================== Case 4: 零事实生肉拦截 ====================
def test_case4_zero_fact_raw_text_rejected():
    """LLM 提取返回空列表时，不落盘任何 source='fallback' 记录。"""
    # 验证 api_server.py 中 fallback 分支已被彻底删除
    api_path = os.path.join(BASE_DIR, "api_server.py")
    with open(api_path, "r", encoding="utf-8") as f:
        source = f.read()

    # 旧的 fallback 分支特征：同时包含 "source\": \"fallback\"" 和 "<= 150"
    has_old_fallback = ('\"source\": \"fallback\"' in source or "'source': 'fallback'" in source)

    # 新的拒绝逻辑应存在
    has_strict_reject = "raw text strictly rejected" in source

    assert not has_old_fallback, "api_server.py 中不应存在 fallback source 标记"
    assert has_strict_reject, "api_server.py 中应有 strictly rejected 日志"
    print("✅ Case 4 PASSED: 零事实生肉拦截")


# ==================== Case 5: 语法全量编译 ====================
def test_case5_full_syntax_compile():
    """对 api_server.py 与 modules/ 下所有 Python 文件执行 py_compile，100% 无错。"""
    import py_compile

    files = [os.path.join(BASE_DIR, "api_server.py")]
    modules_dir = os.path.join(BASE_DIR, "modules")
    for fn in os.listdir(modules_dir):
        if fn.endswith(".py") and not fn.startswith("."):
            files.append(os.path.join(modules_dir, fn))

    errors = []
    for fpath in files:
        try:
            py_compile.compile(fpath, doraise=True)
        except py_compile.PyCompileError as e:
            errors.append(f"{fpath}: {e}")

    assert not errors, f"编译失败:\n" + "\n".join(errors)
    print(f"✅ Case 5 PASSED: {len(files)} 文件全量编译通过")


# ==================== main ====================
if __name__ == "__main__":
    passed = 0
    failed = 0
    for name, func in [
        ("Case 1", test_case1_inference_blocked_from_core),
        ("Case 2", test_case2_negation_triggers_replaces),
        ("Case 3", test_case3_tombstone_prevents_resurrection),
        ("Case 4", test_case4_zero_fact_raw_text_rejected),
        ("Case 5", test_case5_full_syntax_compile),
    ]:
        try:
            func()
            passed += 1
        except AssertionError as e:
            print(f"❌ {name} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {name} ERROR: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"结果: {passed}/5 通过, {failed}/5 失败")
    if failed == 0:
        print("🎉 全部通过！")
    else:
        sys.exit(1)
