"""试验 sqlite-vec 0.1.9 int8/bit 表的正确插入格式。"""
import sys, os, sqlite3, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sqlite_vec
import numpy as np

conn = sqlite3.connect(':memory:')
conn.enable_load_extension(True)
sqlite_vec.load(conn)

# 尝试格式 1: int 列表 JSON
try:
    conn.execute("CREATE VIRTUAL TABLE t1 USING vec0(embedding int8[4])")
    conn.execute("INSERT INTO t1 (rowid, embedding) VALUES (1, ?)", (json.dumps([1,2,3,4]),))
    conn.execute("INSERT INTO t1 (rowid, embedding) VALUES (2, ?)", (json.dumps([5,6,7,8]),))
    r = conn.execute("SELECT rowid, distance FROM t1 WHERE embedding MATCH ? ORDER BY distance LIMIT 2", (json.dumps([1,2,3,4]),)).fetchall()
    print("格式1 int列表JSON: OK", r)
except Exception as e:
    print("格式1 int列表JSON 失败:", e)

# 尝试格式 2: numpy int8 tobytes (BLOB)
try:
    conn.execute("CREATE VIRTUAL TABLE t2 USING vec0(embedding int8[4])")
    v1 = np.array([1,2,3,4], dtype=np.int8).tobytes()
    v2 = np.array([5,6,7,8], dtype=np.int8).tobytes()
    conn.execute("INSERT INTO t2 (rowid, embedding) VALUES (1, ?)", (v1,))
    conn.execute("INSERT INTO t2 (rowid, embedding) VALUES (2, ?)", (v2,))
    r = conn.execute("SELECT rowid, distance FROM t2 WHERE embedding MATCH ? ORDER BY distance LIMIT 2", (v1,)).fetchall()
    print("格式2 np.int8 BLOB: OK", r)
except Exception as e:
    print("格式2 np.int8 BLOB 失败:", e)

# 尝试格式 3: bytes 列表
try:
    conn.execute("CREATE VIRTUAL TABLE t3 USING vec0(embedding bit[8])")
    b1 = bytes([1,0,1,0,1,0,1,0])
    b2 = bytes([0,1,0,1,0,1,0,1])
    conn.execute("INSERT INTO t3 (rowid, embedding) VALUES (1, ?)", (b1,))
    conn.execute("INSERT INTO t3 (rowid, embedding) VALUES (2, ?)", (b2,))
    r = conn.execute("SELECT rowid, distance FROM t3 WHERE embedding MATCH ? ORDER BY distance LIMIT 2", (b1,)).fetchall()
    print("格式3 bytes bit: OK", r)
except Exception as e:
    print("格式3 bytes bit 失败:", e)

# 尝试格式 4: 查询 float32 表用 int8 查询
try:
    conn.execute("CREATE VIRTUAL TABLE t4 USING vec0(embedding float[4])")
    conn.execute("INSERT INTO t4 (rowid, embedding) VALUES (1, ?)", (json.dumps([0.1,0.2,0.3,0.4]),))
    r = conn.execute("SELECT rowid, distance FROM t4 WHERE embedding MATCH ? ORDER BY distance LIMIT 2", (json.dumps([0.1,0.2,0.3,0.4]),)).fetchall()
    print("float 表正常: OK", r)
except Exception as e:
    print("float 表失败:", e)
