# 📜 白泽记忆系统 · 全景演进与架构审计编年史（v1.0 ~ v1.5.3）

## 编年总表（Architecture Changelog）

### 【v1.5.3-hotfix · 天禄·金汤·淬炼】 2026-10-12（生产边界打磨版）
- **核心代号**：天禄·金汤·淬炼（淬火成钢，边界无瑕）
- **动刀背景**：工位全代码走查发现 5 处 P2/P3 级边界隐患，经 GitHub issue 审评批准（#1-#6），一次性修复落地。
- **核心改造**：
  1. **[降级事实过期机制 · Issue #1]**：`raw_fallback` 写入时赋 `expires_at = now + 7d`；`auto_dream.py` 新增 `_cleanup_expired_fallbacks()` 周期巡检，物理删除过期降级事实并同步清理 float/int8 向量，根治无限积累污染库。
  2. **[Recent Pool 防抖硬门槛 · Issue #2]**：`hybrid_recall.py` `_seat_scores` 结果映射后加 `MIN_SEAT_SIMILARITY = 0.15` 防抖门槛，低于阈值不补入候选集。根治短 query（如"那个"）下 Recent Pool 席位挤掉真相关老事实的边界扰动。
  3. **[Hermes 插件层 search 超时优化 · Issue #3]**：`plugin/baize/__init__.py` `_passes_gate` 超时收缩至 2.0s（原 5s），异常或超时一律坚决 Fail-open 放行，确保主对话流丝滑无阻塞。
  4. **[CoreMemory 边界防御 · Issue #4]**：`api_server.py` `_sync_core_memory_from_facts` 防御性编程 `row[0] if row else ""`，消灭非 default 用户首次写入时的无意义 warning 日志。
  5. **[CoreMemory 截断循环 O(n²) 优化 · Issue #6]**：`api_server.py` 采用逆序累加预计算替代 `while` 循环，原实现每次迭代重新 `"\n".join(lines)` 是 O(n²)。新实现 O(n) 更优雅规范。

---

### 【v1.5.3 · 天禄·金汤】 2026-10-12（现役生产实弹版）
- **核心代号**：天禄·金汤（金汤固锁，固若磐石）
- **动刀背景**：白泽底层经历 Qwen 3.8 Max 架构加固与五人专家会诊，彻底根除 SQL 三值逻辑黑洞、L2 单调性失真、WAL 锁竞争崩溃及实体脱落。现与现役生产完全对齐。
- **核心改造**：
  1. **[SQL 三值逻辑修复]**：`hybrid_recall.py` 全局排除 `superseded` 状态时，全量将脆弱的 `NOT IN (SELECT...)` 重构为 `NOT EXISTS (SELECT 1 ...)`，彻底解决 SQLite 子查询含 NULL 时逻辑击穿导致全量失忆的致命黑洞。
  2. **[L2 距离稳健指数映射]**：弃用硬编码线性截断 `max(0, 1 - d/2.0)`，改为自适应单调指数衰减 `math.exp(-d / 0.8)`，确保任意距离下得分平滑且严格单调递减，防止负分与分数阶跃。
  3. **[Recency 时效加法转乘法]**：废除破坏相关性单调性的加性常数增益（`+0.25`），改走单通道乘性相对增益 `score *= (1 + α)`（α≤0.10），彻底根除“低相关新废话凭时效强压高相关老决议”的倒挂现象。
  4. **[活跃记忆池纯准入机制]**：Recent Pool 补入的 48h 内活跃条目废除 `importance*0.4` 假保底分，改由 `_seat_scores` 计算与查询的真实余弦相似度，真相关新决议上浮，无关新闲聊自然沉底。
  5. **[提取端强锚词质检门]**：`llm_extract.py` 新增 `_extract_anchors()` 机制与锚词保留验收；若提取事实漏掉原文关键英文代号/端口/路径，触发纠偏重试（带 Fail-open 保底），根治“用户有三个账号”类无主泛化空壳。
  6. **[WAL 与降级事实防御加固]**：
     - `wal.py` 写入与截断操作全面引入 Fail-open，fsync 异常仅警告绝不反向阻断业务；归档文件名追加毫秒与 UUID 防重名覆盖。
     - `api_server.py` 彻底消灭静默丢失，LLM 提取链失败时自动记录 `raw_fallback` 留存，生肉可追溯；低信息量无实体短句自动降权至 0.3。
  7. **[Jev 门控垂直黑话直通]**：`jev_gate.py` 内置“白泽/10router/nas/7890/hysteria”等垂直工程白名单直通，防止专业黑话被判定为闲聊误杀；读取加 10MB 严格流式保护防 OOM。
  8. **[Reranker 升级]**：全量对齐现役 Voyage `rerank-3-lite`。

---

### 【v1.5.2 · 天禄·轻羽】 2026-09-21（现役正式版）
- **核心代号**：天禄·轻羽（辟邪御灵，轻羽行空）
- **动刀背景**：事实总数突破 6.6 万条（向量 3.2 万条），全量 `fetchall()` 导致常驻内存虚高至 147MB。
- **核心改造**：
  1. **[向量检索游标流式化]**：`modules/hybrid_recall.py` 废除 `fetchall()`，改为 `cur.fetchmany(2000)` 游标分批流式计算。每批仅保留轻量标量并释放原始对象，循环结束后一次性取 Top-k。日常内存暴降至 **75MB ~ 80MB**（降幅 ~46%）。
  2. **[SQLite 缓存硬上限]**：全局 9 处连接注入 `PRAGMA cache_size = -1000`（单连接上限 1MB）与 `PRAGMA mmap_size = 0`，根绝内核脏页沉淀。
  3. **[检索结束即时泄洪]**：检索返回前调用 `ctypes.CDLL("libc.so.6").malloc_trim(0)`，压制 CPython 堆碎片。
  4. **[极限抗压实测]**：通过 `tests/comprehensive_stress_suite.py`（12 线程并发 0 死锁、50 轮检索洪水自动回落、5 大跨领域事实 100% 命中）。

---

### 【v1.5.1 · 天禄·天眼】 2026-09-21
- **核心代号**：天禄·天眼（辟邪御灵，天眼辨真）
- **核心改造**：
  1. **[写入端前置快筛 Jev Ingest Gate]**：引入 TypeSafe Jev 轻量判别器（`modules/jev_gate.py`），在消息聚合写入前以毫秒级判断长期记忆价值，自动拦截闲聊与瞬态废话（`threshold=0.25`），跳过昂贵提取链并削减 70% Token 消耗。
  2. **[召回端智能门神 Search Gate]**：记忆召回重构为 Jev 语义意图判定模型（`search_threshold=0.35`），并挂载 Hugging Face Laya 在线 Space 零鉴权弹性兜底。
  3. **[白名单 0ms 直通与 Fail-open 铁律]**：显式口令（"搜一下/查一下"）与纠正信号（"不对/记错了"）0ms 直通免调网络；外部门控超时（1.5s）或报错时坚决 Fail-open，平滑回退正则，绝不阻塞对话。
  4. **[推理模型调优]**：针对 DeepSeek 等推理模型，在事实提取岗位显式传入 `reasoning_effort="none"`，提速并防吞爆预算。

---

### 【v1.5.0 · 天禄】 2026-09-20
- **核心代号**：天禄（辟邪御灵，永固真如）
- **核心改造**：
  1. **[P0 并发安全]** 重构 `api_server.py` 的 `get_db(write=True)`：注入 `BEGIN IMMEDIATE` 锁住写事务，设置 `synchronous=NORMAL`，彻底消灭读升写死锁；补全显式 `conn.rollback()`。
  2. **[P0 数据持久]** 重构 `modules/wal.py`：在 `append` 和 `mark_complete` 后强制调用 `f.flush()` 与 `os.fsync(f.fileno())`，确保物理落盘，免疫系统断电或 SIGKILL 丢失。
  3. **[认知防线集成]** 固化 Origin 门禁机制、否定即取代极性反转逻辑、`rejected_values` 墓碑防借尸还魂表、零事实生肉硬熔断。
  4. **[版本同步]** 统一代码层 `FastAPI(version="1.5.0")`、`/health` 探针版本串与白皮书三位一体。

---

### 【v1.4.2 · 陆吾·双链】 2026-09-15
- **核心代号**：双链高可用
- **核心改造**：提取器高可用主备链与显式失败拒写；规范 `config.json` 权威键。

---

### 【v1.4.0 ~ v1.4.1 · 陆吾】 2026-08-26 ~ 2026-09-11
- **核心改造**：Voyage 双引擎上线；向量黑洞根除；每日 03:00 两段式解耦容灾。

---

### 【v1.0 ~ v1.3 · 初啼与辟邪】 2026-07-28 ~ 2026-08-20
- **核心改造**：融合 aiduMEM 与玄铁架构；Debian 13 Linux 原生迁移；定名「白泽」。