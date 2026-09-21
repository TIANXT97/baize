# 📜 白泽记忆系统 · 全景演进与架构审计编年史（v1.0 ~ v1.5.1）

## 编年总表（Architecture Changelog）

### 【v1.5.1 · 天禄·天眼】 2026-09-21（现役正式版）
- **核心代号**：天禄·天眼（辟邪御灵，天眼辨真）
- **动刀背景**：解决记忆写入端算力空转/记忆库水化，以及召回端机械正则语义盲区的行业难题，全面集成 System One 决策模型。
- **核心改造**：
  1. **[写入端前置快筛 Jev Ingest Gate]**：引入 TypeSafe Jev 轻量判别器（`modules/jev_gate.py`），在消息聚合写入前以毫秒级判断长期记忆价值，自动拦截闲聊与瞬态废话（`threshold=0.25`），跳过昂贵提取链并削减 70% Token 消耗。
  2. **[召回端智能门神 Search Gate]**：记忆召回重构为 Jev 语义意图判定模型（`search_threshold=0.35`），并挂载 Hugging Face Laya 在线 Space 零鉴权弹性兜底。
  3. **[白名单 0ms 直通与 Fail-open 铁律]**：显式口令（"搜一下/查一下"）与纠正信号（"不对/记错了"）0ms 直通免调网络；外部门控超时（1.5s）或报错时坚决 Fail-open，平滑回退正则，绝不阻塞对话。
  4. **[推理模型调优]**：针对 DeepSeek 等推理模型，在事实提取岗位显式传入 `reasoning_effort="none"`，提速并防吞爆预算。
  5. **[版本同步]**：FastAPI 版本、`/health` 与 `/api/memory/health` 探针、白皮书与架构拓扑全量升至 `1.5.1-baize`。

---

### 【v1.5.0 · 天禄】 2026-09-20
- **核心代号**：天禄（辟邪御灵，永固真如）
- **动刀背景**：引入阶跃星辰 600B MoE 旗舰 Step-5-Preview 深度探伤，由 Claude Opus 担任首席架构终审把关。
- **核心改造**：
  1. **[P0 并发安全]** 重构 `api_server.py` 的 `get_db(write=True)`：注入 `BEGIN IMMEDIATE` 锁住写事务，设置 `synchronous=NORMAL`，彻底消灭读升写死锁；补全显式 `conn.rollback()`。
  2. **[P0 数据持久]** 重构 `modules/wal.py`：在 `append` 和 `mark_complete` 后强制调用 `f.flush()` 与 `os.fsync(f.fileno())`，确保物理落盘，免疫系统断电或 SIGKILL 丢失。
  3. **[认知防线集成]** 固化 Origin 门禁机制、否定即取代极性反转逻辑、`rejected_values` 墓碑防借尸还魂表、零事实生肉硬熔断。
  4. **[版本同步]** 统一代码层 `FastAPI(version="1.5.0")`、`/health` 探针版本串与白皮书三位一体。
- **验收结果**：准出测试题库 5/5 全绿，Opus 终审评定“教科书级正确”。

---

### 【v1.4.2 · 陆吾·双链】 2026-09-15
- **核心代号**：双链高可用
- **核心改造**：
  1. **提取器高可用主备链**：主选 `cbcn/glm-5.3-flash`（经 10router），一级备用 `ss/Atria-Dawn-Preview`，二级备用 `Ling-3.0-flash`。
  2. **显式失败拒写**：提取链全部超时或熔断时显式报错并拒绝入库，坚决不再静默降级为生肉 fallback。
  3. **配置解耦**：规范 `config.json` 中的 7 个权威 `_speed` 键，清理零引用死键。

---

### 【v1.4.0 ~ v1.4.1 · 陆吾】 2026-08-26 ~ 2026-09-11
- **核心改造**：
  1. **Voyage 双引擎上线**：主引擎切换为 Voyage `voyage-4-lite`（1024维，INT8 量化）+ Rerank `rerank-2.5-lite`，BGE-M3 降为冷备。
  2. **向量黑洞根除**：重构 SQLite-Vec INT8 存储与点火直达机制。
  3. **两段式热备**：实现每日 03:00 VM 固态 + 宿主 NAS + 百度网盘两段式解耦容灾。

---

### 【v1.0 ~ v1.3 · 初啼与辟邪】 2026-07-28 ~ 2026-08-20
- **核心改造**：
  1. 融合 aiduMEM 与玄铁架构，确立 9 轨道遗忘衰减与 Cross-Encoder 混合召回；
  2. 完成从 Windows 老家向 Debian 13 Linux 环境的原生迁移；
  3. 彻底清除旧称 `duMem` 残留，系统正式定名「白泽」。