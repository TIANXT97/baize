# 📜 白泽记忆系统 · 全景演进与架构审计编年史（v1.0 ~ v1.6.0）

## 编年总表（Architecture Changelog）

### 【v1.6.1-hotfix】检索层临界共振缺陷整改 2026-10-23（Issue #21）
- **动刀背景**: 10-23 每日金丝雀巡检召回红牌，底层链路（提取/向量/余弦）全程健康，根因定位为检索层两处边界缺陷。
- **核心改造**:
  1. **[FTS5 短语命中不再阻断关键词回退 · Issue #21]**: `hybrid_recall.py` `_fts_search` 两段式逻辑原先在短语命中数 `> 0` 时即终止回退，单条偶然命中的元记忆会扼杀关键词 OR 召回。现新增 `FTS_PHRASE_MIN_HITS = 3`：多实体查询（≥2 个分词）且短语命中数低于该值时，继续尝试关键词 OR。关键词 OR 是短语匹配的超集，BM25 仍会把短语命中项排在前面，无需额外合并去重。
  2. **[Recent Pool 分层配额 · Issue #21]**: 30 个席位拆分为 `RECENT_POOL_IMPORTANCE_SLOTS = 20`（`importance DESC, id DESC`）+ `RECENT_POOL_LATEST_SLOTS = 10`（`id DESC`，纯时效，不受 importance 压制），按 id 去重，时效席位在跳过重叠项后仍补满。高密度写入 0.9 记忆时，0.8 / 0.7 的新记忆不再被整体挤出。`MIN_SEAT_SIMILARITY` 防抖门槛保持不变。
- **质量与测试交付**: 新增 `tests/test_recall_resilience.py`（5 项用例：单条元记忆不阻断回退 / 足量短语命中保持纯短语 / 零命中仍回退 / 低权新记忆保住席位 / 小池无重复）。工位仅做 `py_compile` 与 `pytest --collect-only`，真实执行待 NAS 验证。

### 【v1.6.1】核心数据安全与模块契约闭环整改 2026-10-15
- **核心改造**:
  1. **[启动建表时序前置]**: `api_server.py` 将 `memory_states`、`knowledge_evolution`、`merge_suggestions` 等全量基础表统一收敛至 `init_db()` 中创建，确保表先于索引就位，彻底杜绝空库首次启动报 `no such table` 崩溃。
  2. **[消息角色严格隔离]**: 废除“整批含 user 即全批标记 user”的粗暴逻辑，批量写入逐条按原消息真实 `role` 打 `msg_origin`；CoreMemory 画像入口严格执行 `origin == 'user'` 单条校验，彻底阻断助手推测污染画像。
  3. **[断线补写队列 ACK 保护]**: 插件底层网络异常显式抛出与捕获，仅当服务端返回明确成功回执（ACK）后才允许清除本地 spool，断网时记忆 100% 留存，杜绝静默丢失。
  4. **[AutoDream Write-then-Swap 事务化]**: 记忆合并严格遵循“先写新事实并落盘，后标记旧事实为 superseded”原子原则；合并为空或写入失败时事务整体回滚，旧事实保持 active 状态，杜绝记忆净蒸发。
  5. **[双向量模型空间物理隔离]**: `memory_vec_i8` 增加 `model_space` 列并建立索引；生产库存量 40,300 条历史向量自动平滑归属于 `voyage-4-lite` 空间；检索严格按当前模型空间过滤，跨模型降级（如 BGE）若无同空间向量优雅退回 FTS5，杜绝几何空间混乱比对。
  6. **[重排排序键单向收敛]**: 插件端严格保持服务端 Cross-Encoder Reranker 返回的精排顺序，禁止再次使用粗筛旧 score 逆向重排，算力与精度零损耗。
  7. **[排他写锁生产主链路生效]**: 核心事实写入路径显式传入 `get_db(write=True)`，使 `BEGIN IMMEDIATE` 排他锁在生产并发写入时真实生效，杜绝锁升级冲突。
  8. **[演化确认门槛死区消除]**: 引入差异化门槛字典 `RELATION_THRESHOLDS`（confirms 降至 0.30），打通 `(0.3, 0.5]` Jaccard 相似度区间的确认累加逻辑。
- **质量与测试交付**:
  - 新增对标社区审计报告的硬核测试套件 `tests/test_audit_hardcore_suite.py`（8 项高强破坏性用例 100% PASS）；
  - 全库测试矩阵扩编至 11 套套件、33 项单测，实现全量自动化回归 100% 绿标。

### 【v1.6.0】工程立正与技术规范重构 2026-10-15
- **核心改造**:
  1. **[敏感词脱敏]**: 拔除 `jev_gate.py` 中的硬编码私有关键词元组，重构为可配置的 `custom_whitelist` 机制，提供 `config.example.json` 模板。
  2. **[技术术语统一与立正]**: 彻底废除修真中二命名（天禄、天眼、四道铁壁、潮浪波次等），全面对齐工业级标准描述（分类权重指数衰减、批量防抖聚合、认知安全与墓碑防御）。
  3. **[门控机制通用化]**: 明确双端门控的“决策模型（Decision Model）”抽象定位，解耦单一具体商业服务名称绑定。
  4. **[算法口径自洽]**: 规范 Jaccard 与语义向量在系统内的分层边界，明确字符 Bigram Jaccard 负责低成本结构化判重，主题词覆盖负责长句极性纠错，向量余弦负责深层语义检索。
  5. **[脚手架与文档收拢]**: 清除全库 AI 临时施工注释，历史内部审计报告归档至 `docs/archive/`。

---

### 【v1.5.3-gate · 双子星门控】 2026-10-13(Issue #10 / #11)
- **核心改造**:
  1. **[双子星主备门控 · PR #10]**:`jev_gate.py` 主门控 OpenJev 0.1(26B),备用门控 Drex v2.0(3B MoE)热备接管;母语级中英对齐提示词。
  2. **[备用门控触发边界 · Issue #11]**:主门控超时、HTTP 异常或返回无有效 `answers` 时,`_query_gate` 统一切入备用门控。
  3. **[配置副作用消除 · Issue #11]**:`backup_config` 改为 `JevGate` 构造函数参数,`api_server.py` 不再就地改写 `_jev_cfg`。
  4. **[Laya 链路同构 · Issue #11]**:Laya 兜底补齐代理 `self._opener` 与统一 `User-Agent`,防 Cloudflare 1010 拦截。

---

### 【v1.5.3-hotfix】生产边界打磨 2026-10-12（生产边界打磨版）
- **变更重点**:生产边界打磨
- **动刀背景**：工位全代码走查发现 5 处 P2/P3 级边界隐患，经 GitHub issue 审评批准（#1-#6），一次性修复落地。
- **核心改造**：
  1. **[降级事实过期机制 · Issue #1]**：`raw_fallback` 写入时赋 `expires_at = now + 7d`；`auto_dream.py` 新增 `_cleanup_expired_fallbacks()` 周期巡检，物理删除过期降级事实并同步清理 float/int8 向量，根治无限积累污染库。
  2. **[Recent Pool 防抖硬门槛 · Issue #2]**：`hybrid_recall.py` `_seat_scores` 结果映射后加 `MIN_SEAT_SIMILARITY = 0.15` 防抖门槛，低于阈值不补入候选集。根治短 query（如"那个"）下 Recent Pool 席位挤掉真相关老事实的边界扰动。
  3. **[Hermes 插件层 search 超时优化 · Issue #3]**：`plugin/baize/__init__.py` `_passes_gate` 超时收缩至 2.0s（原 5s），异常或超时一律坚决 Fail-open 放行，确保主对话流丝滑无阻塞。
  4. **[CoreMemory 边界防御 · Issue #4]**：`api_server.py` `_sync_core_memory_from_facts` 防御性编程 `row[0] if row else ""`，消灭非 default 用户首次写入时的无意义 warning 日志。
  5. **[CoreMemory 截断循环 O(n²) 优化 · Issue #6]**：`api_server.py` 采用逆序累加预计算替代 `while` 循环，原实现每次迭代重新 `"\n".join(lines)` 是 O(n²)。新实现 O(n) 更优雅规范。

---

### 【v1.5.3】生产存储加固与检索单调性优化 2026-10-12（现役生产实弹版）
- **变更重点**:生产存储加固与检索单调性优化
- **动刀背景**:白泽底层经过多轮静态代码走查与边界压力测试,彻底根除 SQL 三值逻辑黑洞、L2 单调性失真、WAL 锁竞争崩溃及实体脱落。现与现役生产完全对齐。
- **核心改造**：
  1. **[SQL 三值逻辑修复]**：`hybrid_recall.py` 全局排除 `superseded` 状态时，全量将脆弱的 `NOT IN (SELECT...)` 重构为 `NOT EXISTS (SELECT 1 ...)`，彻底解决 SQLite 子查询含 NULL 时逻辑击穿导致全量失忆的致命黑洞。
  2. **[L2 距离稳健指数映射]**：弃用硬编码线性截断 `max(0, 1 - d/2.0)`，改为自适应单调指数衰减 `math.exp(-d / 0.8)`，确保任意距离下得分平滑且严格单调递减，防止负分与分数阶跃。
  3. **[Recency 时效加法转乘法]**：废除破坏相关性单调性的加性常数增益（`+0.25`），改走单通道乘性相对增益 `score *= (1 + α)`（α≤0.10），彻底根除“低相关新废话凭时效强压高相关老决议”的倒挂现象。
  4. **[活跃记忆池纯准入机制]**：Recent Pool 补入的 48h 内活跃条目废除 `importance*0.4` 假保底分，改由 `_seat_scores` 计算与查询的真实余弦相似度，真相关新决议上浮，无关新闲聊自然沉底。
  5. **[提取端强锚词质检门]**：`llm_extract.py` 新增 `_extract_anchors()` 机制与锚词保留验收；若提取事实漏掉原文关键英文代号/端口/路径，触发纠偏重试（带 Fail-open 保底），根治“用户有三个账号”类无主泛化空壳。
  6. **[WAL 与降级事实防御加固]**：
     - `wal.py` 写入与截断操作全面引入 Fail-open，fsync 异常仅警告绝不反向阻断业务；归档文件名追加毫秒与 UUID 防重名覆盖。
     - `api_server.py` 彻底消灭静默丢失，LLM 提取链失败时自动记录 `raw_fallback` 留存，生肉可追溯；低信息量无实体短句自动降权至 0.3。
  7. **[Jev 门控垂直黑话直通]**：`jev_gate.py` 内置“组件名/端口/网络代理等通用工程白名单”等垂直工程白名单直通，防止专业黑话被判定为闲聊误杀；读取加 10MB 严格流式保护防 OOM。
  8. **[Reranker 升级]**：全量对齐现役 Voyage `rerank-3-lite`。

---

### 【v1.5.2】流式检索与内存轻量化 2026-09-21（现役正式版）
- **变更重点**:流式检索与内存轻量化
- **动刀背景**：事实总数突破 6.6 万条（向量 3.2 万条），全量 `fetchall()` 导致常驻内存虚高至 147MB。
- **核心改造**：
  1. **[向量检索游标流式化]**：`modules/hybrid_recall.py` 废除 `fetchall()`，改为 `cur.fetchmany(2000)` 游标分批流式计算。每批仅保留轻量标量并释放原始对象，循环结束后一次性取 Top-k。日常内存暴降至 **75MB ~ 80MB**（降幅 ~46%）。
  2. **[SQLite 缓存硬上限]**：全局 9 处连接注入 `PRAGMA cache_size = -1000`（单连接上限 1MB）与 `PRAGMA mmap_size = 0`，根绝内核脏页沉淀。
  3. **[检索结束即时泄洪]**：检索返回前调用 `ctypes.CDLL("libc.so.6").malloc_trim(0)`，压制 CPython 堆碎片。
  4. **[极限抗压实测]**：通过 `tests/comprehensive_stress_suite.py`（12 线程并发 0 死锁、50 轮检索洪水自动回落、5 大跨领域事实 100% 命中）。

---

### 【v1.5.1】双端前置判别门控 2026-09-21
- **变更重点**:双端前置判别门控
- **核心改造**：
  1. **[写入端前置快筛 Jev Ingest Gate]**：引入 TypeSafe Jev 轻量判别器（`modules/jev_gate.py`），在消息聚合写入前以毫秒级判断长期记忆价值，自动拦截闲聊与瞬态废话（`threshold=0.25`），跳过昂贵提取链并削减 70% Token 消耗。
  2. **[召回端智能门神 Search Gate]**：记忆召回重构为 Jev 语义意图判定模型（`search_threshold=0.35`），并挂载 Hugging Face Laya 在线 Space 零鉴权弹性兜底。
  3. **[白名单 0ms 直通与 Fail-open 铁律]**：显式口令（"搜一下/查一下"）与纠正信号（"不对/记错了"）0ms 直通免调网络；外部门控超时（1.5s）或报错时坚决 Fail-open，平滑回退正则，绝不阻塞对话。
  4. **[推理模型调优]**：针对 DeepSeek 等推理模型，在事实提取岗位显式传入 `reasoning_effort="none"`，提速并防吞爆预算。

---

### 【v1.5.0】P0 并发安全与物理落盘 2026-09-20
- **变更重点**:P0 并发安全与物理落盘
- **核心改造**：
  1. **[P0 并发安全]** 重构 `api_server.py` 的 `get_db(write=True)`：注入 `BEGIN IMMEDIATE` 锁住写事务，设置 `synchronous=NORMAL`，彻底消灭读升写死锁；补全显式 `conn.rollback()`。
  2. **[P0 数据持久]** 重构 `modules/wal.py`：在 `append` 和 `mark_complete` 后强制调用 `f.flush()` 与 `os.fsync(f.fileno())`，确保物理落盘，免疫系统断电或 SIGKILL 丢失。
  3. **[认知防线集成]** 固化 Origin 门禁机制、否定即取代极性反转逻辑、`rejected_values` 墓碑防借尸还魂表、零事实生肉硬熔断。
  4. **[版本同步]** 统一代码层 `FastAPI(version="1.5.0")`、`/health` 探针版本串与白皮书三位一体。

---

### 【v1.4.2】双链高可用 2026-09-15
- **核心代号**：双链高可用
- **核心改造**：提取器高可用主备链与显式失败拒写；规范 `config.json` 权威键。

---

### 【v1.4.0 ~ v1.4.1】Voyage 双引擎 2026-08-26 ~ 2026-09-11
- **核心改造**：Voyage 双引擎上线；向量黑洞根除；每日 03:00 两段式解耦容灾。

---

### 【v1.0 ~ v1.3】初版与基础架构 2026-07-28 ~ 2026-08-20
- **核心改造**：融合 aiduMEM 与玄铁架构；Debian 13 Linux 原生迁移；定名「白泽」。
