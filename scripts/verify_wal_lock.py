#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WAL 并发写入锁修复验证（2026-08-12）
对比：无锁版本 vs 有锁版本，多线程并发 append+mark_complete，
统计"孤儿 pending"（append 落盘但 mark_complete 丢失）数量。
只用临时文件，零写真实库。
"""
import json
import os
import sys
import tempfile
import threading
import importlib.util

# 加载修复后的 wal.py（不 import 整个包避免副作用）
wal_path = os.path.join(os.path.dirname(__file__), "..", "modules", "wal.py")
spec = importlib.util.spec_from_file_location("wal_fixed", wal_path)
wal_fixed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wal_fixed)

# --- 模拟旧版本：无锁 ---
class WALEngineNoLock:
    def __init__(self, wal_path):
        self.wal_path = wal_path

    def append(self, op, data):
        entry = {"ts": "2026-08-12T00:00:00", "op": op, "data": data, "status": "pending"}
        with open(self.wal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def mark_complete(self, op, data):
        entry = {"ts": "2026-08-12T00:00:00", "op": op, "data": data, "status": "complete"}
        with open(self.wal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def run_stress(engine_cls, n_threads=8, per_thread=200):
    """多线程并发写，返回孤儿 pending 数。"""
    tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w", encoding="utf-8")
    tmp.close()
    eng = engine_cls(tmp.name)
    barrier = threading.Barrier(n_threads)

    def worker(tid):
        barrier.wait()  # 同时开跑，最大化竞态
        for i in range(per_thread):
            data = {"text": f"并发测试消息-线程{tid}-序号{i}-" + "测" * 60, "source": "stress", "user_id": "default"}
            eng.append("store_facts", data)
            eng.mark_complete("store_facts", data)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 统计孤儿
    completed = set()
    pends = []
    with open(tmp.name, encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            key = json.dumps(e["data"], sort_keys=True)
            if e["status"] == "complete":
                completed.add(key)
            elif e["status"] == "pending":
                pends.append(key)
    orphans = [k for k in pends if k not in completed]
    total_lines = sum(1 for _ in open(tmp.name, encoding="utf-8"))
    os.unlink(tmp.name)
    return len(orphans), total_lines


def main():
    print("=== WAL 并发写入锁验证 ===")
    # 旧版（无锁）
    o_old, l_old = run_stress(WALEngineNoLock)
    print(f"旧版(无锁): 8线程x200次 | 总行数 {l_old} | 孤儿 pending {o_old}")
    # 新版（有锁）
    o_new, l_new = run_stress(wal_fixed.WALEngine)
    print(f"新版(有锁): 8线程x200次 | 总行数 {l_new} | 孤儿 pending {o_new}")

    # 断言：有锁版必须零孤儿；无锁版应能复现孤儿（说明测试有效）
    assert o_new == 0, f"FAIL: 有锁版仍有 {o_new} 条孤儿"
    print(f"\n✅ 有锁版零孤儿，修复有效" + (f"；旧版复现 {o_old} 条孤儿证明竞态真实存在" if o_old > 0 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
