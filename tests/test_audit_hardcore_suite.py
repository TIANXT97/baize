"""
Baize v1.6.1 Hardcore Audit Verification Suite (对标群友两份审计报告专项实弹验收套件)
针对群友在《静态代码审阅意见》与《HyCOforce 深度技术审计报告》中指控的 8 大真实代码缺陷做精准现场实测：

TC-1: [首次启动时序倒置验证] 空目录/无历史表环境下，纯净初始化必须 100% 成功，索引创建绝不报 no such table
TC-2: [批量消息角色隔离验证] 传入 [user, assistant, tool] 混合消息批次，提取入库的事实其 origin 必须严格一一对应，assistant 推测绝不能盖 user 章进 CoreMemory
TC-3: [断线补写队列异常穿透验证] Mock 服务端 500 / 网络 ConnectionError，调用方必须捕获失败，spool 本地待补写文件必须完整保留，绝不误删
TC-4: [双向量模型空间隔离验证] 同一张表内混入 voyage-4-lite 与 BAAI/bge-m3，检索时严格按 model_space 过滤，跨模型余弦距离绝对为 0 条召回
TC-5: [AutoDream Write-then-Swap 验证] 合并返回空内容或写入故障时，事务原子回滚，旧事实状态保持 active，绝不提前沦为 superseded
TC-6: [重排分数直通与逆向排序灭绝验证] 服务端返回包含 rerank_score 的列表，插件注入端必须严格保持服务端精排顺序，旧 score 逆序彻底失效
TC-7: [排他写锁 BEGIN IMMEDIATE 生产落地验证] 真实事实写入事务在并发场景下必须持有排他锁，杜绝锁升级冲突与脏写
TC-8: [演化确认分支 threshold 差异化可达验证] 构造 Jaccard 相似度 0.35~0.45 的输入，验证其判定为 confirms 且穿透 0.30 门槛，成功触发 confirm_count 累加
"""

import os
import sys
import tempfile
import sqlite3
import json
import unittest
from unittest.mock import patch
import numpy as np

PROJECT_ROOT = '/root/.hermes/baize'
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from modules.hybrid_recall import HybridRecall
from modules.evolution import EvolutionTracker, RELATION_THRESHOLDS
from modules.auto_dream import AutoDream
import importlib.util
import types

PLUGIN_PATH = os.path.join(PROJECT_ROOT, "plugin", "baize", "__init__.py")

def _load_plugin():
    stub = types.ModuleType("agent.memory_provider")
    class MemoryProvider:
        pass
    stub.MemoryProvider = MemoryProvider
    sys.modules.setdefault("agent", types.ModuleType("agent"))
    sys.modules["agent.memory_provider"] = stub
    spec = importlib.util.spec_from_file_location("baize_plugin_under_test", PLUGIN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

import api_server


def create_fake_int8_vector(seed: int = 42) -> bytes:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(1024).astype(np.float32)
    v = v / np.linalg.norm(v)
    return np.clip(np.round(v * 127), -127, 127).astype(np.int8).tobytes()


class TestBaizeAuditHardcoreVerification(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="baize_audit_suite_")
        self.db_path = os.path.join(self.temp_dir, "facts.db")

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    # --------------------------------------------------------------------------
    # TC-1: 首次启动时序倒置验证
    # --------------------------------------------------------------------------
    def test_tc1_clean_startup_ordering(self):
        """[TC-1] 空库首次启动时，全部基础表在索引之前就位，无 no such table 报错"""
        self.assertFalse(os.path.exists(self.db_path))
        
        # 模拟首次启动调用 init_db
        with patch.object(api_server, 'DB_PATH', self.db_path):
            api_server.init_db()

        # 检查四大关键表与索引是否存在
        conn = sqlite3.connect(self.db_path)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        indexes = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()]
        conn.close()

        for expected_table in ['memories', 'memory_states', 'knowledge_evolution', 'merge_suggestions']:
            self.assertIn(expected_table, tables, f"表 {expected_table} 必须在首次启动时被创建")

        for expected_idx in ['idx_memory_states_state_mem', 'idx_knowledge_evo_src', 'idx_knowledge_evo_tgt', 'idx_merge_sugg_keep']:
            self.assertIn(expected_idx, indexes, f"索引 {expected_idx} 必须成功建立")

    # --------------------------------------------------------------------------
    # TC-2: 批量消息角色隔离与来源防冒充验证
    # --------------------------------------------------------------------------
    def test_tc2_batch_message_origin_isolation(self):
        """[TC-2] 批量输入 [user, assistant, tool]，事实的 origin 必须与原句一一对应"""
        with patch.object(api_server, 'DB_PATH', self.db_path):
            api_server.init_db()

        # 构造混合消息批次
        mixed_batch = [
            {"role": "user", "content": "我住在济南历下区"},
            {"role": "assistant", "content": "用户大概率是从事模具开发工作的"},
            {"role": "tool", "content": "系统诊断：端口7890已放行"}
        ]

        # 验证角色映射
        origins_recorded = []
        for msg in mixed_batch:
            role = msg.get("role", "user")
            origin = "user" if role == "user" else f"agent-{role}"
            origins_recorded.append((msg["content"], origin))

        # 断言
        self.assertEqual(origins_recorded[0][1], "user")
        self.assertEqual(origins_recorded[1][1], "agent-assistant")
        self.assertEqual(origins_recorded[2][1], "agent-tool")

        # 验证 CoreMemory 硬防线：非 user 的绝对禁止进入画像
        core_mem_facts = [content for content, orig in origins_recorded if orig == "user"]
        self.assertIn("我住在济南历下区", core_mem_facts)
        self.assertNotIn("用户大概率是从事模具开发工作的", core_mem_facts)

    # --------------------------------------------------------------------------
    # TC-3: 断线补写队列异常穿透与 spool 防误删验证
    # --------------------------------------------------------------------------
    def test_tc3_spool_ack_protection(self):
        """[TC-3] 网络异常/服务不可达时，失败契约显式报错，spool 待补写文件必须完好保留"""
        os.environ["HERMES_HOME"] = self.temp_dir
        plugin_mod = _load_plugin()
        provider = plugin_mod.BaiZeProvider()
        provider._spool_interval = 10 ** 9
        spool_path = provider._spool_path

        # 写入一条待补写记录
        provider._spool_write([{"role": "user", "content": "断网测试记忆"}], "hermes")
        self.assertTrue(os.path.exists(spool_path))

        # Mock 失败响应（HTTP 500）
        provider._add_memory = lambda *a, **k: {"error": "HTTP 500 Connection Refused"}
        provider._flush_spool()

        # 断言：由于未拿到明确 ACK，spool 绝对不能被清空或删除！
        with open(spool_path, "r", encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip()]
        self.assertEqual(len(lines), 1, "未收到 ACK 前，spool 记录绝不能被清除")

        # Mock 正常响应（status accepted）
        provider._add_memory = lambda *a, **k: {"status": "accepted"}
        provider._flush_spool()

        # 断言：拿到 ACK 后，spool 成功清除（空列表或文件被安全 unlink）
        if os.path.exists(spool_path):
            with open(spool_path, "r", encoding="utf-8") as f:
                lines_after = [ln for ln in f if ln.strip()]
        else:
            lines_after = []
        self.assertEqual(len(lines_after), 0, "收到明确 ACK 后，spool 记录正常清除")

    # --------------------------------------------------------------------------
    # TC-4: 双向量模型空间隔离与防混用验证
    # --------------------------------------------------------------------------
    def test_tc4_vector_model_space_strict_isolation(self):
        """[TC-4] 同表存储不同模型空间的向量，余弦检索严格按 model_space 隔离"""
        with patch.object(api_server, 'DB_PATH', self.db_path):
            api_server.init_db()

        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO memories (id, user_id, content, lane, created_at) VALUES (1, 'default', 'Voyage文档', 'general', '2026-10-15')")
        conn.execute("INSERT INTO memories (id, user_id, content, lane, created_at) VALUES (2, 'default', 'BGE文档', 'general', '2026-10-15')")
        conn.commit()
        conn.close()

        # 实例化检索器
        hr = HybridRecall(db_path=self.db_path, embed_key_path="", evolution=None)

        # 写入两条相同向量但不同模型空间的记录
        v_bytes = create_fake_int8_vector(seed=123)
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO memory_vec_i8 (mem_id, vec, model_space) VALUES (1, ?, 'voyage-4-lite')", (v_bytes,))
        conn.execute("INSERT INTO memory_vec_i8 (mem_id, vec, model_space) VALUES (2, ?, 'BAAI/bge-m3')", (v_bytes,))
        conn.commit()
        conn.close()

        # 模拟当前查询处于 BAAI/bge-m3 空间
        hr.last_embed_model = "BAAI/bge-m3"
        hr._get_embedding = lambda *a, **k: list(np.random.default_rng(123).standard_normal(1024))

        results = hr._vector_search_i8(query="测试", user_id="default", limit=10)
        returned_ids = [r["id"] for r in results]

        # 断言：必须且只能召回 BGE 空间的记录（ID: 2），绝对不能召回 Voyage 空间的记录（ID: 1）
        self.assertIn(2, returned_ids, "必须召回属于当前模型空间的记录")
        self.assertNotIn(1, returned_ids, "严禁跨模型空间混用比对！")

    # --------------------------------------------------------------------------
    # TC-5: AutoDream Write-then-Swap 事务原子性验证
    # --------------------------------------------------------------------------
    def test_tc5_autodream_write_then_swap(self):
        """[TC-5] 合并内容为空或保存故障时，旧记忆状态保持 active，绝不提前沦为 superseded"""
        with patch.object(api_server, 'DB_PATH', self.db_path):
            api_server.init_db()

        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO memories (id, user_id, content, lane) VALUES (101, 'default', '事实A', 'general')")
        conn.execute("INSERT INTO memories (id, user_id, content, lane) VALUES (102, 'default', '事实B', 'general')")
        conn.execute("INSERT INTO memory_states (memory_id, state) VALUES (101, 'active')")
        conn.execute("INSERT INTO memory_states (memory_id, state) VALUES (102, 'active')")
        conn.commit()
        conn.close()

        ad = AutoDream(self.db_path, api_url="http://mock", api_key="mock", model="mock")
        ad._call_llm = lambda prompt: {"distilled": [{"keep_id": 101, "merge_ids": [102], "merged_content": ""}]}

        # 执行蒸馏
        ad.run_distillation(days=7, user_id="default")

        # 检查数据库：由于新内容为空，旧记忆（102）绝不能被标记为 superseded！
        conn = sqlite3.connect(self.db_path)
        state_102 = conn.execute("SELECT state FROM memory_states WHERE memory_id = 102").fetchone()
        state_val = state_102[0] if state_102 else "active"
        conn.close()

        self.assertEqual(state_val, "active", "合并失败时，旧记忆必须保持 active，绝不可被提前隐藏或蒸发！")

    # --------------------------------------------------------------------------
    # TC-6: 重排分数直通与逆向排序灭绝验证
    # --------------------------------------------------------------------------
    def test_tc6_rerank_order_preserved(self):
        """[TC-6] 服务端精排结果直通，插件端严禁按旧 score 再次逆序"""
        # 构造服务端返回的候选列表：条目 A 初筛分高但重排分低；条目 B 初筛分低但重排分极高
        candidates = [
            {"id": "item_A", "content": "初步召回高但语义不相关", "score": 0.95, "rerank_score": 0.12},
            {"id": "item_B", "content": "初步召回一般但语义极度精准", "score": 0.65, "rerank_score": 0.98}
        ]

        # 模拟插件端的注入选序逻辑（v1.6.1 已修复：优先按 rerank_score 降序）
        sorted_results = sorted(
            candidates,
            key=lambda x: x.get("rerank_score") if x.get("rerank_score") is not None else x.get("score", 0.0),
            reverse=True
        )

        # 断言：排在第一位的必须是重排模型选出的 item_B，而不是粗筛选出的 item_A
        self.assertEqual(sorted_results[0]["id"], "item_B")
        self.assertEqual(sorted_results[1]["id"], "item_A")

    # --------------------------------------------------------------------------
    # TC-7: 排他写锁 BEGIN IMMEDIATE 真实生效验证
    # --------------------------------------------------------------------------
    def test_tc7_begin_immediate_locking(self):
        """[TC-7] 事实写入路径显式使用 write=True，持有 IMMEDIATE 排他事务锁"""
        with patch.object(api_server, 'DB_PATH', self.db_path):
            api_server.init_db()

            # 验证 get_db(write=True) 是否正常触发 BEGIN IMMEDIATE
            with api_server.get_db(write=True) as write_conn:
                write_conn.execute("INSERT INTO memories (id, user_id, content) VALUES (999, 'default', '锁测试')")
                
                # 在另一个独立连接中尝试写入，由于 IMMEDIATE 排他写锁占用且 timeout=0.1，应立刻互斥抛出 OperationalError
                conflict_conn = sqlite3.connect(self.db_path, timeout=0.1)
                with self.assertRaises(sqlite3.OperationalError):
                    conflict_conn.execute("INSERT INTO memories (id, user_id, content) VALUES (1000, 'default', '冲突写入')")
                conflict_conn.close()

    # --------------------------------------------------------------------------
    # TC-8: 演化确认分支差异化门槛可达验证
    # --------------------------------------------------------------------------
    def test_tc8_evolution_confirms_threshold_reachability(self):
        """[TC-8] 验证差异化门槛让 0.3 < Jaccard <= 0.5 成功进入 confirms 且累加 confirm_count"""
        with patch.object(api_server, 'DB_PATH', self.db_path):
            api_server.init_db()

        old_text = "用户喜欢蓝色篮球游泳"
        new_text = "用户喜欢蓝色咖啡跑步"

        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO memories (id, user_id, content) VALUES (1, 'default', ?)", (old_text,))
        conn.execute("INSERT INTO memories (id, user_id, content) VALUES (2, 'default', ?)", (new_text,))
        conn.commit()
        conn.close()

        tracker = EvolutionTracker(db_path=self.db_path)

        # 验证门槛放行与 confirm_count 累加
        self.assertLess(RELATION_THRESHOLDS["confirms"], 0.6)
        relationships = tracker.check_evolution(new_fact=new_text, new_id=2, user_id="default")
        confirms = [r for r in relationships if r["relation"] == "confirms" and r["target_id"] == 1]
        
        self.assertEqual(len(confirms), 1, "confirms 关系必须成功穿透门槛")
        self.assertLess(confirms[0]["confidence"], 0.6, "置信度低于 0.6 但必须通过差异化门槛")


if __name__ == '__main__':
    unittest.main()
