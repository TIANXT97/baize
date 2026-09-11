# 白泽 v1.4.1 "陆吾" — AI 思想引擎技术白皮书（正式版）

> **副标题**：全栈免费、工程扎实、运行验证闭环的 Agent 私有记忆引擎
>
> 版本：v1.4.1-BaiZe · 2026-09-11（v1.4 架构攻坚 + 极限健壮性淬炼落地；Voyage 双引擎上线；Ignition 点火直达与向量黑洞根除实装）（2026-08-20 Linux化改造 + 六刀收尾 + 轻量化补丁已同步；2026-08-26 Voyage双引擎上线 · 200M免费终身）
>
> 作者：BaiZe Open Source Community & Hermes Agent
>
> **项目溯源说明**：白泽是基于三个记忆系统的设计思想整合而成的独立产品：
> - **aiduMEM**（v9.3 Aletheia + v10.1 Clotho）：Ebbinghaus 衰减、知识演化、纠正感知、Cross-Encoder Rerank
> - **玄铁记忆架构**（MIMOX）：CoreMemory、AutoDream、Checkpoint、RecallPolicy
> - **伍坞 × 坞忆**：六层记忆体系、受控索引边界、压缩备份理念
>
> 白泽吸收了三者的核心优势，以"全栈免费、功能完整"为目标重新整合。系统旧称 **duMem**，自 v1.0 起正式命名为白泽；v1.1 完成**全量改名收尾**——代码、配置、插件、定时任务、技能文档、命令行脚本中的 duMem 残留全部清除；v1.2 完成**内核加固**——两轮独立代码审查（Claude Code + opencode）发现并修复 24 项高危/中危问题，通过验证断言（留存可复现脚本 38 条），使白泽从"功能齐备"走向"生产级可靠"；v1.3 完成**运行验证与运维闭环**——端到端全链路实测通过、WAL 重放实证生效、哨兵自动重启闭环落地、维护任务零 token 化，白泽进入"全自动稳定运行"阶段。

---

## 一、项目概述

**白泽**（Bai Ze）是一套面向 AI Agent 的**私有化思想引擎**（Thought Engine）。它不是简单的向量数据库，也不是单纯的缓存——它是一个**具备遗忘能力、知识演化意识、结构化记忆管理、自动蒸馏、Cross-Encoder 重排序、写入去重、崩溃恢复和定期治理能力**的完整思想系统。

核心目标：**让 AI Agent 真正像人一样记忆——记该记的，忘该忘的，纠该纠的，织该织的，且在断电后也不丢。**

### 命名体系

采用中国神话命名：

| 代号 | 神祇 | 含义 |
|------|------|------|
| **白泽** | **白泽** | **上古神兽，通万物之情，知鬼神之事，掌管"全知与编织"** |
| **精卫** | **精卫** | **衔木填海，持之以恒——v1.1 填平一切历史遗留（duMem 改名收尾）** |
| **玄武** | **玄武** | **龟蛇合体，镇守四方——v1.2 内核加固（崩溃恢复/数据隔离/输出校验）** |
| **麒麟** | **麒麟** | **祥瑞之兽，象征太平——v1.3 运行验证与运维闭环；v1.3.1 上下文治理（缓存友好/压缩桥/系统提示瘦身）** |
| **陆吾** | **陆吾** | **昆仑山神，掌九域——v1.4 检索自进化（追忆漏斗/点火直达/反馈闭环/结晶闸门，规划中）** |

白泽是上古神话中的神兽，能言语，通万物之情，知天下鬼神之事。以白泽命名记忆系统，寓意：**像白泽一样，知晓一切、记住一切、在需要时想起一切。** v1.1 代号"精卫"，取其"填海不辍"之意；v1.2 代号"玄武"，取其"坚不可摧、镇守不失"之意——本次版本聚焦于**可靠性、正确性、性能**三项内核能力的全面加固；v1.3 代号"麒麟"，取其"祥瑞太平、稳定长存"之意——白泽在修复加固后进入**全自动稳定运行**：自动重启闭环、自动维护、自动验证，无需人工值守。

### 设计哲学

```
"记忆不是堆积，而是筛选。"
"遗忘不是缺陷，而是智慧。"
"思想不是存储，而是编织。"
"全栈免费，功能完整。"
"数据不因崩溃而丢，不因隔离而串，不因幻觉而错。"  ← v1.2 新增
"运行可验证，闭环自运维，无需人值守。"  ← v1.3 新增
```

白泽建立在 **Ebbinghaus 遗忘曲线**的心理学模型之上，引入了**分轨衰减**（Lane-aware Decay）、**知识演化追踪**（Knowledge Evolution Graph）、**用户纠正信号感知**（Correction Detection）、**Cross-Encoder 潮汐重排**、**写入向量去重**、**WAL 崩溃重放**和**定期蒸馏治理**，使得 AI Agent 的上下文注入始终保持**高信噪比**。

---

## 二、版本演进

```
v0.1 初啼 (Day 1)
  → v0.2 FTS5 + 混合召回
    → v0.3 半衰期 + 去重
      → v0.4 相关性闸门
        → v0.5 异步潮浪并忆
          → v0.6 Ebbinghaus 遗忘曲线
            → v0.7 知识演化 + 纠正感知 + 健康报告
              → v0.8 BM25 + 向量融合 + WAL
                → v0.9 CoreMemory + AutoDream + Checkpoint
                  → v1.0 Cross-Encoder Rerank + 白泽命名
                    → v1.1 精卫：性能优化 + 写入去重 + 定期治理 + 全量改名
                      → v1.2 玄武：内核加固（崩溃重放/数据隔离/输出校验/打分校正）
                      → v1.3 麒麟：运行验证闭环（端到端实测/哨兵自运维/WAL 实证）
                        → v1.3.1 麒麟：上下文治理（缓存友好/压缩桥/系统提示瘦身）
                          → v1.4 陆吾：检索自进化（追忆漏斗/FTS预过滤/WAL熔断/死锁消除）
                            → v1.4.1 陆吾：极限健壮性淬炼（点火直达Ignition/压缩桥向量闭环/LRU线程锁/13项实弹大检阅100%全通）
```

| 版本 | 代号 | 关键里程碑 |
|------|------|-----------|
| v0.1 | 初啼 | SQLite + FTS5 + 初始数据导入 |
| v0.2 | 混合召回 | FTS5 中文全文索引 + 5 维加权融合 |
| v0.3 | 半衰期 | 时间衰减 + 去重 + 矛盾检测 |
| v0.4 | 闸门 | 相关性闸门 + 纠正信号感知 |
| v0.5 | 潮浪 | 异步潮浪并批 + 会话合并 |
| v0.6 | Lethe | Ebbinghaus 遗忘曲线 + 分轨衰减 |
| v0.7 | Aletheia | 知识演化追踪 + 纠正感知 + 健康报告 |
| v0.8 | Prometheus | BM25 + 向量融合 + WAL 预写日志 |
| v0.9 | Synapse | CoreMemory 3-block + AutoDream 蒸馏 + Checkpoint 快照 |
| v1.0 | 白泽 | Cross-Encoder Rerank 潮汐重排 + 全栈免费方案 + 产品化命名 |
| v1.1 | 精卫 | 写入误杀修复 + embedding 缓存 + 写入去重 + /api/cleanup 治理 + 周维护 cron + duMem 全量改名 |
| **v1.2** | **玄武** | **两轮审查 + 四批修复 24 项（A 双写一致性 / D 崩溃重放+隔离+校验 / B+ 性能 / C 打分）+ 验证断言全过（留存 38 条）** |
| **v1.3** | **麒麟** | **运行验证闭环：端到端全链路实测 + WAL 重放实证（218 条）+ 哨兵自动重启 + 维护任务零 token 化** |
| **v1.3.1** | **麒麟** | **上下文治理：L1 注入缓存友好 + L2 压缩阈值 40% + L3 压缩桥归档（on_pre_compress + /api/ingest）+ 系统提示瘦身（4 工具集 + 65 skill 禁用）** |
| **v1.3.2** | **麒麟** | **Linux化改造 + 六刀收尾 + 轻量化（2026-08-20）：systemd 用户服务 + 环境变量化 + WAL 2M轮转 + Coalesce留尾 + secret零衰减 + 门控口令 + AutoDream日/周 + 每日宿主备份 03:00 + 孤儿向量清零 + LRU 256）** |
| **v1.4** | **陆吾** | **检索自进化与死锁根治：search_trace 追忆漏斗 + FTS 废弃预过滤 + 复合索引性能暴涨14倍 + 写事务剥离外部I/O彻底根治死锁 + 全局30s防爆排队 + WAL死信熔断与全文无损** |
| **v1.4.1** | **陆吾** | **极限健壮性淬炼与点火实装（2026-09-11）：点火直达机制（Ignition秒回）+ /api/ingest 压缩桥向量双写闭环 + LLMExtractor LRU线程锁 + Voyage 1024维强约束 + user_profile 矛盾清洗整行截断 + 四维13项实弹压测100%全通（Claude Opus 4.6终审Production-Ready）** |

**版本说明**：v0.1-v0.9 为内部迭代版本。v1.0 为首个公开版本；v1.1 为性能与治理版本；v1.2 为**可靠性内核加固版本**——由两轮独立深度审查驱动（Claude Code 首轮 + opencode 二轮），修复了 WAL 重放失效、跨用户数据隔离缺失、LLM 输出未校验等**深层数据安全缺陷**，以及连接风暴、打分失真、参数越界等性能与正确性问题。

---

## 三、系统架构

### 3.1 总体架构

```
┌─────────────────────────────────────────────────────────┐
│                   AI Agent (Hermes)                      │
│                                                         │
│   ┌──────────────────────────────────────────────────┐  │
│   │           Context Injection (三级注入)             │  │
│   │  CoreMemory (每轮) → Checkpoint (新会话·规划中) → 检索   │  │
│   └──────────────────────────────────────────────────┘  │
│                         │                               │
│            ┌────────────┼────────────┐                  │
│            ▼            ▼            ▼                  │
│     Recall Gate    Hybrid Recall   Rerank              │
│     (相关性闸门)    (BM25+向量)     (Cross-Encoder)      │
│            │            │            │                  │
│            └────────────┼────────────┘                  │
│                         ▼                               │
│                 sqlite-vec 向量检索                      │
└─────────────────────────────────────────────────────────┘
          │                       │
          ▼                       ▼
┌──────────────────┐   ┌──────────────────────┐
│   sqlite-vec     │   │   SQLite 数据库        │
│  (向量存储)       │   │                      │
│  Voyage 4-lite 主│   │  facts.db            │
│  + bge-m3 兜底    │   │  (记忆 + FTS5 + 向量) │
│  1024维 32K上下文 │   │  + WAL 预写日志重放    │
│  + LRU 256 缓存   │   │                      │
└──────────────────┘   └──────────────────────┘
```

### 3.2 检索链路（v1.2 更新）

```
用户查询
  │
  ▼
相关性闸门 (Recall Gate)
  │  ├─ 纠正信号检测："不对/记错了" → 强制检索
  │  ├─ 短追问继承：<15字 + <15s → 继承上轮结果
  │  ├─ 问句检测：含疑问词/问号 → 触发检索
  │  └─ 短确认跳过："好/收到/ok" → 跳过检索
  │
  ▼
Hybrid Recall (BM25×0.3 + 向量×0.5 + graph×0.2)
  │  ├─ FTS5 全文检索（trigram 分词，v1.2：打分不再恒 1.0，绝对量度×位次衰减）
  │  ├─ sqlite-vec 向量检索（Voyage voyage-4-lite 1024维 32K 主用 + bge-m3 兜底，input_type=query/document 分衣，int8 量化 + float32 兜底）
  │  │    └─ embedding LRU 缓存（v1.1 512→v1.3 256/3600s，线程安全锁 v1.2，Voyage 2000 RPM 解锁后 1.9s/批）
  │  ├─ 图谱扩展（v1.1 P1-2：1-2 跳联想，v1.2：补乘 age 衰减 + 置信度路径连乘）
  │  ├─ superseded 排除（v1.2：查询侧 JOIN 过滤，向量/去重路径统一生效）
  │  └─ 分数融合排序（v1.2：importance 只计 1 次，不再三重叠加）
  │
  ▼
Top-N 候选 → Cross-Encoder Rerank (Voyage rerank-2.5-lite 32K 主用 + bge-reranker-v2-m3 兜底，LRU 100/300s)
  │  ┌─────────────────────────────────────┐
  │  │ 每对 (query, doc) 独立打分          │
  │  │ Cross-attention 捕捉精细语义        │
  │  │ 按得分重新排序 Top-K                │
  │  └─────────────────────────────────────┘
  │
  ▼
Ebbinghaus 衰减过滤 → superseded 排除 → 上下文注入（v1.2：relevance 键统一）
```

**v1.2 检索核心变化**：
1. **打分修正**：FTS 相关度从"候选集内 min-max（最优恒 1.0）"改为**绝对量度 × 位次衰减**——弱匹配不再虚高（实测强查询 relevance 0.333 vs 弱查询 0.038）
2. **importance 去重计**：importance 只由 `decay.get_score` 计入一次（修复前搜索路径额外叠加 `importance×0.2`，实际计 3 次）
3. **图谱扩展补 decay**：关联记忆补乘自身年龄衰减，陈旧记忆不再被抬进 top-k（实测 400 天前关联记忆分数 ≈0.000 vs 新记忆 0.0010）
4. **superseded 查询侧排除**：`find_duplicate`、`_vector_search_i8/f32` 三处 SQL 统一排除 superseded——被取代的记忆不再当作"重复"拦截新写入，也不占 top-k 槽位
5. **连接风暴治理**：图谱扩展改为批量 `IN` 查询（`_get_memories_by_ids`，每批 200），检索连接数从 O(节点数) 降到 O(调用数)

### 3.3 写入链路（v1.2 更新）

```
每轮对话结束 (sync_turn)
  │
  ▼
内容分类 (仅基于用户消息，v1.1 修复误杀)
  │  ├─ preference / lesson / technical → 写入
  │  └─ temporary（纯时效询问）→ 跳过
  │
  ▼
潮浪并批 (coalesce：tech 2.5s 空闲 / 8s 窗口 / 6 条 1500 字符)
  │
  ▼
LLM 事实抽取 (Ling-3.0-flash，15s 超时) + FastPath 正则
  │
  ▼
批内文本级预筛 (v1.2 B5：Jaccard>0.9 免 embedding，省 2N 次 API 调用)
  │
  ▼
写入去重 (向量距离 < 0.05 → 跳过；v1.2：批内先文本去重再 embedding)
  │
  ▼
INSERT memories + FTS5 同步 + 向量双写入库 (v1.2 A1：float+int8 同事务原子)
  │
  ▼
知识演化检测 (v1.2 D3：user_id 隔离 + 归属校验)
  │
  ▼
WAL 预写日志 (v1.2 D1：崩溃后启动自动重放，幂等保护)
```

**v1.2 写入核心变化**：
1. **WAL 真重放（D1）**：修复前 `wal.replay()` 只取回 pending 打日志、从不重新执行——崩溃即丢批数据。v1.2 实现完整重放：启动时对 pending 按 op 重新执行（已存在→直接 mark_complete，失败单条仅 warning 不阻塞启动），实测 208 条 pending 重放成功、0 失败
2. **LLM 输出校验（D2）**：AutoDream 的 `superseded`/`keep_id`/`merge_ids` 必须属于本批 `batch_ids` 且归属正确，非法 ID 直接丢弃并记 warning——模型幻觉不再能误删/覆盖任意记忆
3. **跨用户隔离（D3）**：evolution / auto_dream / find_duplicate 全链路 user_id 化——A 用户的合并、演化、去重不再影响 B 用户数据
4. **双写一致性（A1）**：float + int8 向量同事务写入，任一失败整体回滚；清理路径同步清 int8
5. **去重批量化（B5）**：批内先文本级预筛（Jaccard>0.9），只有幸存者进 embedding 去重——多 fact 消息从 2N 次 API 调用降到 ~N 次

**WAL 重放失败语义（v1.4 澄清，GLM-5.2 审查回应）**：
- 双层 WAL 的协调：SQLite WAL（引擎层，防磁盘页损坏）与 wal.jsonl（应用层，管"记账→调 LLM 提取→写库→销账"业务链）职责分离、互不依赖——wal.jsonl 的 `append` 在 LLM 提取后、写库前（L332），`mark_complete` 在写库+向量+演化全部成功后（L374），窗口内任何一步崩溃即留下 pending
- 幂等键：`_memory_exists(text[:100], user_id)`——content 前 100 字符 + user_id 精确匹配，防重复写入
- **失败条目语义**：重放单条失败仅记 warning **不销账**（pending 保留，供下次启动重试）——**不存在"静默丢失"路径**；也不会无限循环（重放只在启动时执行一次，每次失败条数若持续存在会在日志留下 warning 可追踪）
- 已存在条目：直接 mark_complete 跳过（不重复调 LLM，实测日常重放秒级）

---

## 四、功能清单

### 4.1 核心能力矩阵

| 能力 | 模块 | 版本引入 | 说明 |
|------|------|:---:|------|
| 向量语义检索 | sqlite-vec + bge-m3 | v0.1 | 1024维向量，语义相似度匹配 |
| 中文全文检索 | FTS5 | v0.1 | trigram 分词，关键词精确匹配 |
| 混合检索 | hybrid_recall.py | v0.2 | BM25×0.3 + 向量×0.5 + graph×0.2 融合 |
| 相关性闸门 | memory_gate.py | v0.4 | 纠正信号、问句、任务意图、短确认 |
| 异步潮浪并批 | coalesce.py | v0.5 | 多句合并一次抽取，省 token |
| Ebbinghaus 衰减 | decay.py | v0.6 | 指数衰减，9轨道分轨 |
| 知识演化追踪 | evolution.py | v0.7 | replaces/enriches/confirms/challenges |
| 纠正信号感知 | memory_gate.py | v0.7 | "不对/记错了" 强制检索 |
| 健康报告 | api_server.py | v0.7 | /api/memory/health |
| BM25+向量融合 | hybrid_recall.py | v0.8 | 关键词 + 语义 + importance 融合 |
| WAL 预写日志 | wal.py | v0.8 | JSONL 预写，原子操作 |
| CoreMemory | core_memory.py | v0.9 | LLM 可编辑 3-block |
| AutoDream | auto_dream.py | v0.9 | 7天自动蒸馏（LLM + 规则引擎 fallback） |
| Cross-Encoder Rerank | reranker.py | v1.0 | bge-reranker-v2-m3 重排序（含 LRU 缓存） |
| Voyage 向量主用 | hybrid_recall.py | v1.4 | voyage-4-lite 1024维 32K + input_type query/document，bge-m3 兜底，200M 终身免费 |
| Voyage 重排主用 | reranker.py | v1.4 | rerank-2.5-lite 32K 主用 + bge-reranker 兜底，200M 终身免费，2000 RPM 解锁 |
| 向量全量重烙 | scripts/voyage_reembed_all.py | v1.4 | 16,535 条 document 衣重烙 0.8M tokens（0.4% 免费池），1.9s/批 980s 完成 |
| 写入分类误杀修复 | plugins/baize/__init__.py | v1.1 | 仅按用户消息分类，正则锚定时效短语 |
| prefetch 最新查询覆盖 | plugins/baize/__init__.py | v1.1 | 旧线程接力处理新查询 |
| CoreMemory 缓存 | plugins/baize/__init__.py | v1.1 | TTL 60s，不再每轮请求 |
| embedding LRU 缓存 | hybrid_recall.py | v1.1 | 512条/1h，同查询提速 91% |
| 写入向量去重 | hybrid_recall.py + api_server.py | v1.1 | 相似度 > 0.975 跳过写入 |
| 记忆治理清理 | api_server.py /api/cleanup | v1.1 | 衰减归档 + 孤儿向量清理 + WAL 轮转 |
| 周维护自动调度 | Hermes cron | v1.1 | 每周日 03:15 自动蒸馏 + 清理 |
| EvolutionTracker 复用 | hybrid_recall.py | v1.1 | 检索不再每次新建实例 |
| **WAL 崩溃重放** | **wal.py + api_server.py** | **v1.2** | **启动自动重放 pending，幂等保护，崩溃不丢数据** |
| **LLM 输出 ID 校验** | **auto_dream.py** | **v1.2** | **幻觉 ID 拦截，防误删/覆盖记忆** |
| **跨用户数据隔离** | **evolution/auto_dream/hybrid_recall** | **v1.2** | **全链路 user_id 化 + 归属反查** |
| **向量双写一致性** | **hybrid_recall.py** | **v1.2** | **float+int8 同事务原子，清理同步清两表** |
| **int8 检索优化** | **hybrid_recall.py** | **v1.2** | **user_id 预过滤 + argpartition top-k + 坏 blob 容错** |
| **FTS 打分校正** | **hybrid_recall.py** | **v1.2** | **绝对量度×位次衰减，弱匹配不再虚高** |
| **参数钳制** | **api_server.py + auto_dream.py** | **v1.2** | **consolidation 阈值 clamp，防负值清库** |
| **API 错误处理** | **api_server.py** | **v1.2** | **HTTPException 400/500，不泄露内部异常** |

### 4.2 9轨道分轨衰减

| 轨道 | 衰减策略 | 半衰期 | 用途 |
|------|---------|--------|------|
| identity | 永不衰减 | ∞ | 用户身份信息 |
| preference | 永不衰减 | ∞ | 用户偏好 |
| procedural | 快速衰减 | ~230天 | 程序性记忆 |
| rule | 中等衰减 | ~138天 | 规则和约定 |
| lesson | 中等衰减 | ~138天 | 教训和经验 |
| evidence | 中等衰减 | ~99天 | 证据类信息 |
| knowledge | 正常衰减 | ~69天 | 知识性信息 |
| emotion | 快速衰减 | ~46天 | 情感记忆 |
| general | 正常衰减 | ~69天 | 通用信息 |

**关于永不衰减轨道的膨胀控制**：永不衰减的2个轨道（identity/preference）通过 AutoDream 蒸馏机制控制膨胀。AutoDream 会识别这些轨道中的重复、过时、可合并记忆，执行合并/标记操作。"永不衰减"指不因时间自动衰减，但可通过知识演化和蒸馏主动清理。**v1.2 起**，蒸馏的合并/标记操作均经过 LLM 输出校验（D2）与用户归属校验（D3），杜绝误操作。

### 4.3 CoreMemory 3-block

| Block | 说明 | 更新方式 |
|-------|------|---------|
| user_profile | 用户画像（姓名、职业、位置、偏好） | LLM 可编辑 |
| current_project | 当前项目（任务、进度、文件） | LLM 可编辑 |
| key_decisions | 关键决策（设计选择、技术选型） | LLM 可编辑 |

每轮对话自动注入到 system prompt，确保 Agent 始终了解用户和项目状态。v1.1 起插件侧增加 60 秒 TTL 缓存，避免每轮重复请求。

### 4.4 AutoDream 自动蒸馏

**运行方式**：每周1次（周日 03:15），由 Hermes 定时任务「白泽周维护」调用 `/api/auto-dream` 端点触发，与「Memory自动压缩」（周日 03:00）错开 15 分钟，避免竞争 LLM 配额。

**处理流程**：
1. 获取最近7天的记忆（v1.2：按 user_id 过滤）
2. 分批（每批20条）调用 LLM 分析
3. LLM 识别重复、过时、可合并的记忆
4. **v1.2 D2 校验**：LLM 返回的 superseded/keep_id/merge_ids 必须属于本批 batch_ids，非法丢弃并记 warning；`_update_content` 检查 rowcount，更新不存在行不计数
5. 执行合并/标记/蒸馏（v1.2：合并后自动重建 float+int8 向量，检索语义不失效）
6. LLM 部分批次失败时，失败批次用规则引擎（Jaccard）兜底
7. LLM 全部失败时，整体 fallback 到规则引擎

**异步执行**：`/api/auto-dream` 默认异步执行（`async_mode=true`），立即返回 `job_id`，通过 `/add/job/{job_id}` 轮询结果。**v1.2 B8**：jobs 字典 30 分钟 TTL 自动清理，不再无限积累。

**LLM 模型**：Ling-3.0-flash（蚂蚁百灵官方 API，免费）

**单次消耗**：
- 输入：~24,000 tokens
- 输出：~2,000 tokens
- 费用：¥0（免费）

### 4.5 Checkpoint 会话快照（设计方案）

**状态说明**：Checkpoint 为设计文档层面的方案（11段会话快照），由 Hermes Agent 侧负责生成与读写（白泽服务端不承载独立 checkpoint 模块）。当 Agent 侧实现后，通过白泽 workspace 目录持久化。

**11段结构**：

| 段 | 内容 | Token 预算 |
|---|------|-----------|
| §1 Active intent | 用户最新请求原文 | 500 |
| §2 Next action | 下一步具体操作 | 1,000 |
| §3 Directives | 人设规则 + 项目规则 | 800 |
| §4 Task tree | 任务层级列表 | 1,000 |
| §5 Current work | 当前工作描述 | 2,000 |
| §6 Files/code | 涉及的文件和代码 | 1,500 |
| §7 Discovered | 会话关键发现 | 2,000 |
| §8 Errors/fixes | 踩坑记录 | 1,500 |
| §9 Live resources | 运行时状态 | 1,000 |
| §10 Decisions | 设计决策 | 3,000 |
| §11 Open notes | 杂项 | 800 |
| **总计** | | **~15,100** |

### 4.6 Cross-Encoder Rerank 潮汐重排

**问题**：Bi-Encoder（bge-m3）对精细语义差异（否定词、时态、细微偏好变化）捕捉不够精准。

**方案**：在 Hybrid Recall 之后、Ebbinghaus 衰减之前，插入 Cross-Encoder Rerank 阶段。

**模型**：BAAI/bge-reranker-v2-m3（硅基流动免费 API）

**性能**：
- 延迟：~300ms
- Token：~1,200 tokens/次
- 触发方式：**每次搜索都触发**（实时重排序，非批处理）
- 缓存：LRU 100 条 / 5 分钟 TTL

### 4.7 v1.1 优化详情（2026-07-31 实施，全部实测验证）

#### P0-1 写入分类误杀修复（插件端）

**问题**：`_classify_content` 用子串匹配判断"临时观察"，词表包含"现在/搜索/查一下/运行/执行/帮我写"等高频词，且判断对象是**用户消息 + AI 回复的合并文本**——只要任意一方含这些词，整轮对话被判定 temporary 丢弃。实测"现在"一词几乎出现在每句话中，导致大量工作记录从未写入记忆库。

**修复**：
1. 判断对象改为**仅用户消息**（AI 回复不参与分类）
2. 临时观察改为**正则锚定**的纯时效短语（`^(现在几点|今天几号|今天天气|…`）
3. 删除"现在/搜索/运行/执行/帮我写"等误杀词

**验证**：修复后"我喜欢用 DeepSeek"正常落库为 preference。

#### P1-1 embedding LRU 缓存（服务端）

**问题**：每次向量搜索都调用外部 embedding API（硅基流动），搜索延迟 = 网络往返；API 故障时向量召回全空。

**修复**：`_get_embedding` 增加 LRU 缓存（512 条 / 1 小时 TTL / ~2MB 内存）。**v1.2 B3 加固**：缓存读写加 threading.Lock（网络请求在锁外），消除多线程 check-then-act 竞态。

**实测**：同一查询 441ms → **42ms，提速 91%**。

#### P1-2 prefetch 最新查询覆盖（插件端）

**问题**：后台搜索线程存活期间新查询被丢弃，导致注入的是上一轮查询的陈旧结果。

**修复**：`queue_prefetch` 增加 `_pending_query` 接力机制——旧线程完成后自动处理最新查询，注入永远是最新结果。

#### P1-3 CoreMemory TTL 缓存（插件端）

**问题**：每轮同步 prefetch 都额外请求 `/api/core-memory`（每轮 2 个 HTTP 请求），且该表内容极少变化。

**修复**：60 秒 TTL 缓存。

#### P1-4 LLM 抽取超时收紧（服务端）

**问题**：LLM 抽取超时 30 秒 × 2 次重试 = 最长 60 秒阻塞（`baize_add` 同步路径）。

**修复**：超时收紧至 15 秒（Ling-3.0-flash 正常 <5s），失败走既有 fallback（存原文）。

#### P2-1 写入向量去重（服务端）

**问题**：近 7 天增长 799 条，其中大量近似重复（演化关系 enriches 达 193 条），数据膨胀快。

**修复**：写入前对新事实做向量相似度检查，与已有记忆距离 < 0.05（相似度 > 0.975）则跳过并记日志。**v1.2 B5 增强**：批内先文本级预筛（Jaccard>0.9），只有幸存者进 embedding 去重。

**实测**：重复写入返回空列表，日志 `Dedup skip: #935 d=0.000`。

#### P2-2 EvolutionTracker 实例复用（服务端）

**问题**：每次 `/search` 都新建 EvolutionTracker 实例并重复执行建表 DDL。

**修复**：全局实例复用，通过构造函数注入。

#### P0-2 记忆治理机制（服务端 + 调度）

**问题**：Ebbinghaus 衰减只在检索打分中生效（降权），但 `should_archive()` 从未被调用——**记忆只进不出**；WAL 的 `cleanup()` 也从未被调用，日志文件无限增长。

**修复**：
1. 新增 `POST /api/cleanup` 端点：扫描衰减分数 < 0.1 的记忆标记 superseded（identity/preference 零衰减天然豁免）+ 清理 superseded 孤儿向量（**v1.2 A2：同步清理 int8 表**）+ 轮转 WAL（7 天保留）
2. Hermes 定时任务「白泽周维护」（每周日 03:15）：`/api/auto-dream` 蒸馏 + `/api/cleanup` 清理，与「Memory自动压缩」（03:00）错开

**收益**：数据量保持数千条量级，检索性能不随时间劣化。

### 4.8 v1.2 内核加固详情（2026-08-03 实施，四批 24 项，验证断言全过）

**验证可复现性（2026-08-04 补充）**：D/B+/C 三批验证脚本已留存至 `baize/scripts/`（`verify_baize_D.py` / `verify_baize_B.py` / `verify_baize_C.py`，临时库执行、零写真实库，合计 38 条断言覆盖 D1-D3/B1-B8/C1-C8 全部修复项，运行方式：`venv/Scripts/python.exe scripts/verify_baize_*.py`）；批次 A 见 `verify_a_consistency.py`；E/F 批见 `verify_e1-e4.py` / `verify_f1-f3.py`。

**背景**：v1.1 发布后，进行两轮独立深度代码审查——Claude Code 首轮（发现 int8 双写/清理残留等）+ opencode 二轮（发现 WAL 重放失效、跨用户隔离缺失、LLM 输出未校验等首轮漏掉的重磅问题）。全部修复由 opencode 执行（`--auto` YOLO 模式），代码备份于 `baize/backup-review-0803/`，每批独立验证，**服务重启由飞书端 SYSTEM 权限哨兵自动完成**。

#### 批次 A：高危修复（双写一致性 + 清理 + 残留清零）

| # | 修复项 | 说明 |
|---|--------|------|
| A1 | **int8/float 双写一致性** | `_vector_search` int8 结果不足 limit 时用 float32 补齐（不再短路）；`store_vector` float/int8 同事务、任一失败整体回滚返回 False；补漏坏 blob 跳过 + 不足补齐叠加的盲区 |
| A2 | **清理同步清 int8** | `delete_fact` 与 `/api/cleanup` 删 float 时同步删 `memory_vec_i8`；migrate 脚本末尾孤儿对账 |
| A3 | **905 条残留清零** | 历史 superseded 死向量全部清理，float/int8 两表行数对齐、交叉孤儿 0（清理前备份 `facts.db.pre-cleanup-20260803.db`）|
| A4 | **int8 检索优化** | user_id 预过滤（JOIN memories）、np.argpartition 取 top-k、坏 blob 跳过该行并 warning |
| A5 | **迁移脚本健壮性** | 分批 500 行 commit、busy_timeout=5000、幂等（开头清空 i8）、结束校验 ok==float_count 非零退出 |

#### 批次 D：新高危修复（opencode 二轮审查发现，12 条留存断言全过）

| # | 修复项 | 风险等级 | 说明 |
|---|--------|:---:|------|
| D1 | **WAL 重放实现** | 🚨 高危 | 修复前 `wal.replay()` 只取回 pending 打日志、从不重新执行——崩溃即丢批数据（历史实测存在从未应用的 pending）。实现完整重放：`_replay_wal_pending` 对 pending 按 op 重新执行（已存在→直接 mark_complete，失败单条 warning 不阻塞）；幂等预检 `_memory_exists`；`replay()` 顺序修复（pending 先于 complete 时误报）。**实测：多次重启累计重放（8-3 19:04 的 208 条 / 23:57 的 218 条 / 8-4 00:36 的 3 条 / 08:55 的 14 条），全部 failed=0** |
| D2 | **AutoDream LLM 输出 ID 校验** | 🚨 高危 | 修复前 LLM 幻觉的 superseded/keep_id/merge_ids 直接执行，可把无关记忆标 superseded 或覆盖 content。新增 `_coerce_id` 规范化 + 必须属于本批 batch_ids，非法丢弃 warning；`_update_content` 检查 rowcount==0 不计数 |
| D3 | **跨用户数据隔离** | 🚨 高危 | 修复前 evolution / auto_dream / find_duplicate 均无 user_id 过滤——A 用户操作可静默改 B 用户数据。全链路 user_id 化：`_get_recent_memories*`/`_find_similar`/会话合并/`_store_candidates`/`check_evolution`/`get_related`/`find_duplicate` 全部按用户隔离；merge_suggestions/knowledge_evolution 无 user_id 列，写入前反查 memories 校验归属；auto-dream/consolidate 端点加 user_id 参数（默认 "default" 兼容旧行为）|

#### 批次 B+：性能与一致性（11 条留存断言全过）

| # | 修复项 | 说明 |
|---|--------|------|
| B1 | **检索连接风暴** | 新增 `_get_memories_by_ids`（WHERE id IN，每批 200 防变量上限），图谱扩展改批量取行；search 末尾 superseded 过滤改 `is_superseded_batch`；连接数从 O(节点数) 降到 O(调用数) |
| B2 | **get_related 健壮性** | LIMIT 去掉/Python 侧按 max_per_hop 截断（防 hub 节点饿死其它分支）；多跳 confidence 按路径连乘（实测 0.8×0.6=0.48）；`_fts_search`/`_get_memory` conn 泄漏补 try/finally |
| B3 | **embedding 缓存线程安全** | `_embed_cache` 加 threading.Lock，读/写/淘汰在锁内、网络请求在锁外；实测 8 线程 × 30 次并发无异常 |
| B4 | **合并后向量重建** | `run_distillation` 把 `{keep_id, content}` 收集进 `rebuilt` 返回；api_server 新增 `_rebuild_vectors()`，auto-dream 同步/异步两条路径完成后调 `store_vector` 重建 float+i8 双写——合并后检索语义不过期 |
| B5 | **去重批量化** | `_batch_text_dedup`（Jaccard>0.9，复用 auto_dream._jaccard_similarity）批内预筛，只有幸存者进 find_duplicate——多 fact 消息 2N 次 embedding 降到 ~N 次；实测 4 条（2 重复+1 近似+1 不同）→ 2 条 |
| B6 | **superseded 查询侧排除** | 三处 SQL（find_duplicate、_vector_search_i8、_vector_search_f32）加 `NOT IN (SELECT memory_id FROM memory_states WHERE state='superseded')`——被取代记忆不再拦截新写入、不占 top-k；存量向量立即失效，存储回收由 /api/cleanup 兜底 |
| B7 | **量化公共函数 + 流式迁移** | 新建 `modules/quantize.py` 公共 `quantize_int8`（bytes 直接 np.frombuffer，去掉 tolist 往返），两处行为一致；migrate 改 fetchmany(BATCH) 流式——**顺带修复真 bug**：同一游标 executemany 会丢弃未读完的 SELECT 行（首版只写 500/1249 条） |
| B8 | **jobs 字典 TTL** | 新增 `_purge_old_jobs(ttl=1800)`，/add 异步、auto-dream 异步、get_job_status 三处调用——完成超 30 分钟条目自动清理 |

#### 批次 C：打分正确性与 API 收尾（15 条留存断言全过）

| # | 修复项 | 说明 |
|---|--------|------|
| C1 | **FTS 打分虚高** | 去掉候选集内 min-max（最优恒 1.0），改**绝对量度 × 位次衰减**：`relevance = exp(-k·|rank|/(|rank|+H+1)) · H/(H+alpha)`（k≈2，**alpha=5（E2 调整，原 10）**），另加 count 查询取真实命中总数（不受 LIMIT 截断）；实测强查询 0.333 vs 弱查询 0.038，无恒 1.0 |
| C2 | **importance 三重复计** | search() 删除 `importance×0.2` 叠加（importance 已由 decay.get_score 计入）；实测 hi/lo 打分精确等于 fts_score×0.3，高低 importance 比值 8.70（≈decay 一次计入）|
| C3 | **图谱扩展绕过 decay** | 图谱扩展对 related 记忆补乘 `decay.get_score(lane, created_ts, access_count, importance)`（`_get_memories_by_ids` 补查 access_count）；实测 400 天前关联记忆 ≈0.000 vs 新记忆 0.0010 |
| C4 | **参数钳制** | `run_session_consolidation`：非数值抛 ValueError、minutes=max(1,·)、dup=clamp(0,1)、cand=clamp(0,dup)；API 层非法类型 → HTTPException(400)——负阈值不再能整窗互相 supersede |
| C5 | **Jaccard 剪枝** | consolidation 窗口 bigram→ids 倒排索引，只对共享 ≥1 bigram 的对算 Jaccard（不共享必为 0，精确剪枝）；剪枝版结果与暴力 O(n²) 完全一致 |
| C6 | **API 错误处理** | consolidate/auto-dream 同步/cleanup 三端点异常统一 HTTPException(500, "…failed")，不泄露内部异常串；参数校验 400（实测 "secret path" 未外泄）|
| C7 | **响应 schema 统一** | vector(i8/f32)、graph、FTS-only 降级路径全部补 `relevance` 键（vector=余弦/相关度，graph=None）|
| C8 | **候选批量查重** | `_store_candidates` 批量归属校验（`_owned_ids`）+ 一次 `(keep_id,other_id) IN` 批量查重（替代 N+1）；两个调用方落库前过滤 other_id ∈ 本批 superseded；**顺带修复**批量查重占位符生成 bug（`",".join("(?,?)"*n)` 按字符 join 产生 SQL 语法错误）|

**过程中发现的额外 bug**：C8 批量查重占位符生成、B7 同游标 executemany 丢行——均在修复中一并解决。

### 4.9 v1.3 运行验证与运维闭环（2026-08-04 实测，全部实证）

| # | 项目 | 实测结果 |
|---|------|---------|
| V1 | **端到端全链路验证** | 写入（/add → LLM 抽取 → 落库 #4713）→ 检索（/search 命中，score 0.3225）→ 清理（/facts/4713 删除无残留），全链路通过 |
| V2 | **WAL 重放实证** | 多次重启累计重放全部成功：8-3 19:04 的 208 条、23:57 的 218 条、8-4 00:36 的 3 条、08:55 的 14 条，**全部 failed=0**（208/218 分属不同重启事件）——D1 修复从代码层面实证生效 |
| V3 | **哨兵自动重启闭环** | 8-3 18:40 哨兵检测桌面端完成信号 → SYSTEM 权限自动重启 baize → 健康验证 → 飞书汇报，全程无人工介入 |
| V4 | **维护任务零 token 化** | 数据库体检 + 系统健康检查合并为 no_agent 脚本哨兵（每 6h，零 token）；周维护/触发器守卫/月度维护均为脚本模式 |
| V5 | **数据快照（8-4 实测）** | 记忆 4,630 条（general 3,880 / evidence 210 / procedural 172 / preference 121 / identity 91 / knowledge 105 / rule 28 / emotion 14 / lesson 9），superseded 913，向量 float=i8=3,721（双写一致），演化边 552（enriches 530 + replaces 19 + confirms 3），今日写入 71 条，当日零错误 |
| V6 | **持续稳定性** | 服务 ok / 5 探针全绿 / 无 degraded / 进程 ~73 MB / 今日零错误 |

**v1.3 意义**：白泽从"修复完成"走向"验证可靠、自动运维"——四批修复不是终点，**运行实证才是交付标准**。V1-V6 六项实证构成完整证据链：能写、能查、能清、能恢复、能自愈、能汇报。

### 4.10 v1.3 同日修复（批次 E/F，2026-08-04 实施，7 项）

**背景**：opencode 一致性审查（GLM-5.2）在核对白皮书与源码时发现 v1.3 当日另有 E/F 两批 7 项实质修复（任务简报 `TASK_E_0804.md` / `TASK_F_0804.md`，备份 `backup-audit-0804/` 与 `backup-audit-0804-f/`，验证脚本 `verify_e1-e4.py` / `verify_f1-f3.py`），本版白皮书补记。

#### 批次 E：检索与写入链路校正（4 项）

| # | 修复项 | 说明 |
|---|--------|------|
| E1 | **分类体系 9 类对齐** | LLM 提取 prompt 从 4 类扩到 9 类（与 LANE_CONFIG 对齐：identity/preference/emotion/lesson/rule/procedural/evidence/knowledge/general）+ 每类中文示例；`_store_extracted_facts` 的 category 归一化 + lane 计算兜底链（category ∈ LANE_CONFIG 直接用，否则 classify_lane，再兜底 general）。**修复前 lesson/rule/procedural/knowledge 等 lane 永远提不出来（95% 落 general）** |
| E2 | **三来源量纲对齐** | VEC/FTS/GRAPH 权重常量化（`VEC_WEIGHT=0.5 / FTS_WEIGHT=0.3 / GRAPH_WEIGHT=0.2`）；FTS hit_factor alpha 10→5（弱查询不再被整体压低）。修复前 vector 独大、graph 纯陪跑，混合检索名存实亡 |
| E3 | **门控误杀修复（显式搜索旁路）** | `memory_gate.py` 新增 `EXPLICIT_SEARCH_PATTERNS`（`^(帮我查\|查一下\|搜一下\|找找\|看看\|翻一下)\S*` 等），显式搜索意图在 MEMORY_TRIGGERS 之前匹配直接放行；`/search` 端点支持 `skip_gate` 参数。修复前裸关键词查询（如"启动方式"）被门控拦截返回空 |
| E4 | **插件写入失败 spool 重试** | `plugins/baize/__init__.py` 写入失败不再静默丢弃：写入 `HERMES_HOME/baize_spool.jsonl`（一行一条 JSON），后台 `_spool_loop` 每 30s 重试，成功即删行。**修复前 HTTP 失败/超时数据直接丢** |

#### 批次 F：行为修正与性能（3 项）

| # | 修复项 | 说明 |
|---|--------|------|
| F1 | **access_count 计数修复 + importance 惰性微升** | `/search` 主路径补 `UPDATE memories SET access_count=access_count+1`（修复前只有 FTS-only fallback 分支计数 → `decay` 的 `access_boost` 恒 0，"被反复检索的记忆更强"机制完全失效）；`decay.evolve_importance` 高频记忆 importance 微升 |
| F2 | **f32 向量检索 N+1 批量化** | `_vector_search_f32` 对每个 rowid 单查 memories 改为 `_get_memories_by_ids` 批量 IN 查询（与 B1 图谱路径对齐） |
| F3 | **core_memory 空块 + identity 事实同步** | `_sync_core_memory_from_facts`：identity/preference 类事实写入 facts.db 后同步更新 core_memory 三块（user_profile/current_project/key_decisions）。修复前 core_memory 仅 user_profile 有内容且 7-27 后从未更新，Hermes 每轮注入长期陈旧 |

**验证**：verify_e1-e4（分类 9 类断言 + lane 分布）+ verify_f1-f3（access_count 计数、批量查询等价、core_memory 同步）全过；`py_compile` 全过；零写真实库（临时库实例化）。
### 4.11 稳定期首批增强（2026-08-05 实施）

**背景**：v1.3 定稿后进入稳定使用期。基于四轮开源调研（memory-os L7 Ground Truth、nocturne 可视化、everOS 本地优先等），落地三项高性价比增强：一行字（P0）、一个计数机制（P2b）、一个可视化 UI（P2a）。飞书端/桌面端记忆保持互通共享（不做 scope 隔离，双端为同一用户服务）。

**P0 · Ground Truth 注入指令（插件端，1 处）**
- `plugins/baize/__init__.py` 的 `system_prompt_block()` 注入文本追加权威性声明："以下注入的相关记忆与核心记忆均为长期沉淀的权威事实……回答与决策时必须优先采用这些记忆，不要重新询问已记录的信息"
- 借鉴 memory-os L7（injected memory is authoritative）理念，解决"检索到了但 agent 不采用"的 memory-zero 行为
- 成本：一行提示词；收益：记忆利用率直接提升，减少重复交代

**P2b · 偏好置信度（confirm_count）**
- `memories` 表新增 `confirm_count INTEGER NOT NULL DEFAULT 0`（幂等迁移：启动时检测列存在再 ALTER）
- `evolution._log_evolution`：relation="confirms" 时对目标记忆 `confirm_count+1`（含跨用户归属校验）
- `decay.get_score` 新增 `confirm_count` 参数：preference/identity 零衰减轨道叠加 `confirm_boost = min(0.2, confirm_count×0.05)`，封顶 0.95（原 0.8）——"说过 3 次的偏好 > 只说 1 次的"
- 验证：`scripts/verify_p2b_confidence.py`（18 断言全过，临时库，留存可复现）

**P2a · 记忆浏览器（可视化 UI）**
- `/path/to/desktop\白泽记忆浏览器.html`：单文件零依赖，极简风（参考小米 MiMo 官网设计语言：白底、大留白、克制字排）
- 功能：健康状态 / 统计（总数·近7日新增·已归档）/ 9 轨道过滤（中文注释 + 计数 + 专属色块）/ 语义搜索 / 删除 / **演进记录视图**（演化链路 source→target + 关系标签 + 置信度）/ 30 秒自动刷新（可开关）/ 每页条数切换 / 动态版本页脚
- 新增只读端点 **`GET /api/evolution/records`**（knowledge_evolution 联表 memories，按时间倒序，默认 50 条）
- 服务端加 **CORS** 支持（本地浏览器 file:// 直连 8767）

**配套维护**：opencode 更新至 1.18.13、bun 1.3.14 安装（插件自动更新通道）、清理 3 个僵尸 opencode 进程。

**8-5 实测数据**：facts.db 40.3 MB，记忆 7,060 条，演化边 840 条，superseded 916 条——首个完整运行日零错误，E1 分类修复后 lane 分布健康（general 占比降至 ~59%，evidence 966 / procedural 643 / knowledge 418）。

### 4.12 上下文治理三件套 + 系统提示瘦身（2026-08-07 实施，双端验证通过）

**背景**：长会话上下文膨胀 → 全量上传费 token；压缩后信息丢失；白泽检索注入有缓存命中顾虑。GitHub 对标调研（Letta/MemGPT 24k⭐ 的 Memory Pressure + Archival 机制、mem0 62k⭐ 的注入稳定性、CAG 分级注入、LMCache KV 缓存层）后落地四层治理。

**L1 · 缓存友好（插件 `_do_search`）**
- 注入结果去 `[score]` 前缀 + `(score↓, id↑)` 稳定排序——注入块文本不再随相似度分数微抖，prompt 前缀缓存命中率最大化
- 关键认知：白泽注入在 **user 消息内**（fenced block，非 system prompt）——system prompt 与历史消息缓存照常命中，注入变化只影响当前消息（1-2K token）；score 前缀是唯一的抖动源

**L2 · 压缩阈值 40%**
- `compression.threshold` 0.5 → **0.4**：平均上下文水位 45K → 38K（每请求输入省 ~15%）
- 论证：30% 是负优化（压缩频率 ×3 + 缓存失效 ×3 + 工作记忆变短 + protect_last_n 空转）；DeepSeek 系缓存命中价 ≈ 未命中 1/10——**缓存命中率优先于阈值激进下调**

**L3 · 压缩桥（信息不丢）**
- Hermes 原生钩子 `on_pre_compress(messages)`（MemoryProvider 接口）：压缩丢弃旧消息前调用，返回字符串注入压缩摘要
- `BaiZeProvider.on_pre_compress()`：规则式提取（对话 300 字 / 工具输出 200 字截断、最近 60 条、≤20 条、内容去重，**零模型成本**）→ HTTP 调白泽新端点归档
- 白泽新端点 **`POST /api/ingest`**：不走 coalesce/LLM 直接落库（快、零额外成本），同 user 同 content 去重跳过，`source=compression` 标记，lane 白名单校验
- 效果：**工具输出 / 中间事实压缩前归档，压缩后不蒸发**；压缩摘要出现 `[压缩归档] 已归档 N 条` 痕迹
- 实测：端点插入 2 / 去重跳过 1 ✅；真实压缩触发归档 18 条（source=compression）✅

**S · 系统提示瘦身**
- 禁用 4 个闲置工具集（bfl / computer_use / image_gen / tts）+ **65 个零使用 skill**（累计 80 个禁用，含 arxiv / github 全家 / notion / docx 等，全部可恢复）+ 记忆条目合并
- 预期 system prompt 减 ~25%（28-40K → 22-30K token），每轮底价下降——配置备份 `config.yaml.bak-slim-0807-1128`

**7 天 token 全景实测（2026-07-31 → 08-07，insights 数据）**：
- 总消耗 **7.73 亿 token**（deepseek-v4-flash 占 94%）；输入 1,213 万 → **Total/Input ≈ 64 倍**——绝大多数 token 花在每轮重复上传历史 + 缓存读取，L1/L2 直击该大头
- 平台分布：desktop 5.56 亿 / feishu 1.74 亿 / cli 3,052 万 / cron 1,056 万（cron 仅占 1.4%）
- 最长会话 3.1 天烧 101 万 token——**长任务完成及时开新会话**（白泽记忆兜底，不怕失忆）

**生效时机铁律**：插件代码与 config 为**进程级加载**——L1/L3 需重启 Hermes 桌面端，L2 配置下个会话生效，白泽服务端（/api/ingest）重启一次即生效；飞书 gateway 为独立服务进程，需单独重启（`schtasks /run /tn HermesRestartGateway`）同步生效。

### 4.13 知识星图（2026-08-10 实施，拓扑可视化）

**背景**：参照 aiduMEM「MAP 心图」（知识域星图）——把记忆演化关系画成可交互拓扑图。白泽的优势：连线不是无差别聚类，而是**带语义的演化边**（enriches 强化 / replaces 替换 / confirms 确认，各带置信度）。

**数据底子**（实测）：`knowledge_evolution` 1,490+ 条边（enriches 97.7% / replaces / confirms），涉及 ~1,800 节点，平均置信度 0.78，8 个轨道有边。

**后端**：新增只读端点 `GET /api/graph/subgraph`（api_server.py，~120 行）：
- 参数：`q`（关键词→FTS 种子，LIKE 兜底）/ `lane`（轨道过滤）/ `top_n`（默认 120，上限 300）/ `max_edges`（默认 240，上限 800）/ `hops`（1-2，BFS 沿演化边扩展）/ `user_id`
- 无 q：按 `importance × degree` 取高分节点；有 q：种子 + `evolution.get_related` BFS 扩展
- 边取两端均在节点集内的，置信度降序截断；`meta.truncated` 标记防蜘蛛网
- 实测：无参 80 节点/120 边；q=上下文 16 节点/3 边；lane 过滤精确；无结果空态正常

**前端**（`/path/to/desktop\白泽记忆浏览器.html`）：演进页新增 Tab「演进列表 ⇄ 知识星图」（方案 A，首屏中央集控五面板零改动）：
- **ECharts 5**（`echarts.min.js` 与页面同目录外部引用，~1MB 完整版；因体积未内嵌，双文件同目录双击离线可用）
- 力导向布局：节点色 = 轨道专属色（9 色统一体系），节点大小 = 度数+重要度；边色 = 关系类型（强化绿/替换琥珀/确认蓝），边宽 = 置信度
- 交互：缩放/拖拽/悬停 tooltip（内容+轨道+重要度+连接数）/点击节点 → 右侧详情卡（内容/轨道/重要度/连接数）
- 工具栏：主题搜索（Enter 触发）、轨道筛选、跳数选择（1/2）、图例、节点/边计数 + 截断提示
- 全部动效尊重 `prefers-reduced-motion`

**验证**：端点四路（无参/q/lane/空结果）全过；页面三视图（高分节点/关键词子图/轨道子图）实测正常。

**风险记录**：ECharts 完整版 1MB（原估 500KB）→ 改为外部引用不内嵌；演化边集中在 enriches 属数据现状，图例如实呈现。

### 4.14 v1.4 检索自进化路线图（2026-08-10 规划，陆吾）

**来源**：aiduMEI 作者开源（`monkey2jack/aiduMEI`，v18.2 Zeus）——白泽设计思想源头的后续演进。已 clone 源码逐文件验证（`cache/aidumei-src/`），四项能力全部源码级确认。详细排期见 `/path/to/desktop\白泽记忆系统\白泽v1.4规划.md`。

| P | 项 | 内容 | 工作量 | 借鉴源码 |
|---|-----|------|--------|---------|
| P0 | **search_trace 追忆漏斗** | search() 五阶段打点（候选池→融合→去重→衰减→最终，count+ms），`/search_trace` 端点 | 低·半天 | `recall_funnel.py` |
| P1 | **Ignition 点火直达·安全化**【认知治理审查 · 增加约束】 | 相似度 ≥0.85 的记忆跳过衰减管道直接保送（max 8，权重 1.5x）；**5 条 AND 约束缺一不可**：非 superseded / 无未解决冲突 / 排除零衰减轨道（identity/preference 本不衰减）/ 来源可信度允许（embedding 相似推断类不可点火）/ 时效有效——不是"≥0.85 就保送" | 低·半天 | funnel 内嵌 |
| P1.5 | **Provenance + Memory 状态模型**【认知治理审查 · 新增 · EvolveMem 前置】 | 来源可信度分级（用户明确陈述/纠正=最高 → embedding 相似推断=不能作为事实来源）；检索结果携带 source/status/confidence/confirmed 元数据（memories 表 source 列 + memory_states 表增量扩展）；Ground Truth 注入折中：仅在低置信/有冲突/已废弃时附 warning 标记（保 L1 缓存优化成果）；**EvolveMem 前置条件——没有来源锚点，自进化就是盲学** | 中·1 天 | 自有 |
| P2 | **EvolveMem 反馈闭环**【认知治理审查 · 反馈信号分级】 | 三表（queries/feedback/adjustments）+ `/api/evolve/feedback` + 6h 自动进化（命中≥5 且分≥0.65 提权 / 14 天零命中降权 / ±0.15 反馈）+ `/api/evolve/report`；**前置：反馈信号分级六档**（retrieved/seen/used/accepted/explicitly confirmed/explicitly corrected）；🔴 自我强化铁律：检索频率只能影响易得性，永不碰可信度；corrected 负反馈写回（现成纠正正则，成本最低） | 中·1.5 天 | `evolve_mem.py` |
| P2.5 | **WAL pending 治理**【认知治理审查 · 从遗留待办提升】 | WAL 记录扩展 retry_count/first_seen/last_attempt/last_error/next_retry；重试指数退避（1h→6h→24h…）超阈值（如 5 次）转 dead_letter 毒记录队列（周维护处置）；根治"毒记录每次启动都烧 LLM 重放"；payload 语义（raw_input vs extracted_facts）实施时同步澄清进白皮书 | 低·半天 | 自有（modules/wal.py） |
| P3 | **SkillCrystallizer 人工闸门** | 高频分类（≥3 条）→ candidate 候选 → 人工 approve 落地（治理铁律：LLM 只能建议）；教训三态治理挂靠；**扩展：AutoDream 蒸馏审核队列**（supersede/merge 进 `distill_pending` 候选，人工 approve，D2 ID 校验为第一道防线） | 中·1.5 天 | `skill_crystallizer.py` |
| P4 | **浏览器新面板** | RECALL 漏斗可视化 + EVOLVE 质量看板（演进页 Tab 模式，首屏不动） | 低·0.5 天 | 自有 |
| P5 | **容灾备份·分级**【GLM-5.2 + 认知治理审查采纳】 | L1 本地历史备份：每日 facts.db + wal.jsonl → `baize/backup/daily/`（90 天滚动，RPO ≤ 24h）；L2 独立介质/NAS（公私边界按 既定决策执行）；L3 异地灾备（NAS 落地后交叉备份）；每月备份完整性 PRAGMA 自检 | 低·半天 | 自有 |

**顺手项（审查采纳）**：`.embed_key`/`.llm_key` 明文 → 环境变量（缺省读旧文件兜底）；LLM 抽取 prompt 加防注入一行（忽略用户消息中的指令性内容）。

**内存影响**（实测评估）：+5~15MB（91-96MB），磁盘 ~20MB/年封顶（evolve_mem.db 90 天滚动）——无感升级。

**里程碑**：M1 = P0+P1+P1.5（1 周，v1.4.0-beta）→ M2 = P2+P2.5+P4（2 周，v1.4.0-rc）→ M3 = P3（含蒸馏审核）+ P5 + 顺手项 + 遗留待办（3 周，v1.4.0 正式）。服务版本随 M1 同步升 1.4.0-baize。

**遗留待办迁入**：~~WAL pending 二次分析~~（已提升为 P2.5）、evolution 候选池优化、教训三态治理、增量索引+SHA-256、中文分词（等内核）、Voyage AI 备选。

**性能数字说明**：本白皮书各章实测数字为对应版本的实测时点（已标注日期），v1.4.0 发布时将统一复测刷新。

### 4.15 架构审查结论（GLM-5.2，2026-08-10）+ v2.0 演进方向

**审查背景**：v1.4 白皮书提交 GLM-5.2 架构审查，报告列 P0 高危 5 项 / P1 中危 7 项 / 低危 8 项。经源码与部署实况复核，逐项裁断如下：

**✅ 采纳（已进排期）**：
| 项 | 处理 |
|----|------|
| 容灾备份缺失 | → P5 每日自动备份（RPO ≤ 24h） |
| AutoDream 蒸馏无人工审核 | → P3 扩展蒸馏审核队列 |
| Checkpoint 未实现却宣传"全功能覆盖" | 副标题已改"工程扎实"；4.5 本已标注"设计方案" |
| 版本号混乱（v1.4 规划 vs 服务 1.3.1） | 标题注明"规划版"；v1.4.0 落地后版本三处同步 |
| 双层 WAL 协调未说明 | → §3.3 补"WAL 重放失败语义"（幂等键/失败不销账/无静默丢失路径） |
| 性能数字时点不统一 | 上文加统一复测说明 |
| API Key 明文存储 | → 顺手项：移环境变量 |
| prompt 注入防护 | → 顺手项：抽取 prompt 防注入一行 |

**❌ 驳回（场景不匹配，记录在案）**：
| 项 | 理由 |
|----|------|
| 鉴权缺失（P0） | 服务监听 127.0.0.1 本机回环，局域网不可达；单用户系统，暴露面=本机进程，威胁极低 |
| HTTPS / SQLCipher 加密 | 本机回环 + 单用户，传输与存储均为自有磁盘；收益 < 复杂度成本 |
| 单点架构不可扩展 / 多租户 / 分库分表 | 单用户系统无需横向扩展；演进路线见下方 v2.0 方向 |
| 监控独立化（Prometheus 看门狗） | 社区既定决策：不挂额外看门狗，Hermes 哨兵体系即监控闭环 |
| 数据合规（GDPR/个保法） | 私人单用户系统，无第三方数据处理义务 |
| SLA/SLO 定义 | 个人工具无合同义务，以实测数字代替承诺 |

**v2.0 演进方向（纯规划文字，不实施）**：若未来部署形态变化（多用户 / NAS 多端 / 跨机器），优先补：① API Token 鉴权（user_id 从鉴权上下文派生）；② PG+pgvector 或 SQLCipher 迁移路径评估；③ 异步启动重放（服务先监听、重放降级返回）；④ 数据导出/删除 API。触发条件：出现第二个真实用户或跨机器访问需求。
### 4.16 架构审查结论（认知治理，2026-08-10）

**审查背景**：v1.4 白皮书提交认知治理架构审查（审查报告归档 `审查与对比/白泽v1.4架构审查报告（认知治理）.md`）。核心命题：系统从"稳定的记忆系统"进入"检索自进化"阶段后，关键问题不再是"能不能正确检索"，而是——**"系统根据什么证据改变自己的检索策略，以及错误是否会被反馈闭环不断强化"**。

**✅ 采纳（已进排期，详见规划文档）**：
| 项 | 处理 |
|----|------|
| 检索频率 ≠ 事实可信度（P0 核心） | P2 前置"反馈信号分级六档"（retrieved→explicitly corrected）+ 🔴 自我强化防线铁律：**检索频率只能影响易得性（importance/decay/access_count），永远不能影响可信度（confidence）**；现有 access_count→importance 进化（10 次/档 +0.05 封顶 0.9）即"检索频率影响权重"雏形，EvolveMem 不得放大 |
| Ignition 是"抗衰减机制"不是"直通车"（P0） | P1 升级安全化：5 条 AND 约束（非 superseded / 无冲突 / 排除零衰减轨道 / 来源可信 / 时效有效）——语义相似（≥0.85）区分不了"在用 X / 已改用 Y"，必须与 superseded/冲突治理联动 |
| Provenance 前置（P0.5） | 新增 P1.5：来源可信度分级 + 检索结果携带 source/status/confidence 元数据，**插在 EvolveMem 之前**（自进化学的是有来源锚点的数据，不是盲学） |
| Ground Truth 权威性膨胀 | P1.5 注入折中：只在低置信/有冲突/已废弃时附加 warning 标记，正常高置信度注入保持原样（保 8-07 L1 缓存优化成果） |
| corrected 负反馈未写回 | P2 第一档落地：插件现成纠正信号正则（不对/记错了/wrong）升级为写回负向标记到被引用记忆（成本最低） |
| 永久失败跨启动反复重放 | 新增 P2.5 WAL pending 治理：retry_count / 指数退避 / dead_letter 毒记录处置 |
| WAL 语义歧义（payload 存 raw_input 还是 extracted_facts） | P2.5 实施时同步澄清进白皮书（§3.3 WAL 重放失败语义已先行落地） |
| 本机备份 ≠ 真正灾备 | P5 分级：L1 本地历史 → L2 独立介质/NAS（公私边界按 既定决策执行）→ L3 异地（NAS 交叉备份） |

**源码层补充核实**（审查为纯白皮书视角，实施前已对照现有实现）：access_count→evolve_importance 即自我强化雏形；corrected 正则已存在、当前仅用于门控放行；identity/preference 本就是零衰减轨道（Ignition 排除项）；单次启动只重放一次 WAL 已有（防单次无限循环），缺的是跨启动永久失败治理。

详细排期与设计见 `规划与方案/白泽v1.4规划.md`。



### 4.17 Linux化改造（2026-08-19 实施，Debian 13，Windows→Linux 迁移后）

**背景**：白泽自 Windows 老家 `E:\\AI工具\\Hermes\\baize` 搬至飞牛 VM `192.168.1.100` `/root/.hermes/baize`，老家仅留文档与备份，VM 为唯一运行实体。

| 项 | 改造 | 说明 |
|---|---|---|
| **启动源唯一化** | NSSM → `systemd --user baize.service` | `WorkingDirectory=/root/.hermes/baize` `ExecStart=/usr/bin/python3 api_server.py` `Restart=always` `RestartSec=5` `WantedBy=default.target`；`loginctl enable-linger root` 开机自启，无需登录即起；`XDG_RUNTIME_DIR=/run/user/0` 补齐 DBUS（SSH/工具终端必备） |
| **密钥环境变量化** | `.embed_key/.llm_key` → `Environment=BAIZE_EMBED_KEY / BAIZE_LLM_KEY` | 代码改环境变量优先、文件兜底（`api_server.read_key(path, env_name)` + `hybrid_recall.__init__`）；改 key 只改 `baize.service` 的 Environment 行 → `daemon-reload` → `restart baize` |
| **抽取示例 Linux化** | `llm_extract.py EXTRACT_PROMPT` | 原 NSSM/`E:\\AI工具` 示例换成 `systemd/journalctl` 示例，防 LLM 误学旧环境 |
| **平台适配** | `_trim_memory()` | `win32` 走 `ctypes.CDLL("ucrtbase.dll")._heapmin()`，Linux 走 `ctypes.CDLL("libc.so.6").malloc_trim(0)`；日志 `Memory trim: gc + heap compaction done` 即生效；`grep -rn "\.dll" baize/` 可扫残留 |
| **残留清理** | 删除 | `start_service.bat`、0 字节 `memory.db`、`e2e_tmp.py`、`test_coalesce.py`、根目录 `server.log` 已删 |
| **向量扩展补齐** | Linux 重装 | `pip install --break-system-packages sqlite-vec numpy -i https://pypi.tuna.tsinghua.edu.cn/simple`；`systemctl --user restart baize` 使 `HAS_SQLITE_VEC=True`；`backfill_vectors.py` 补 9331 条存量向量 |
| **文档库新址** | 宿主 `/data/backup/baize/` | VM 副本 `/root/baize-docs/白泽记忆系统/`；Windows 旧址 `E:/Desktop/白泽记忆系统/` 仅历史 |

**教训**：迁移后先 `grep -rn "\\.dll\|nssm\|E:/\|pythonw"` 扫 Windows 残留；key 改造后验证 `systemctl --user show-environment` 与 `/health` 探针。

### 4.18 六刀收尾（2026-08-20 实施，前五刀实测 + 第六刀每日宿主备份）

**背景**：08-20 上午五刀已钉完，第六刀“每日对齐到宿主保险柜”压着，宿主 `记忆备份` 目录 `/data/backup/baize` 已建。

| 刀 | 名头 | 落点 | 验证 |
|---|---|---|---|
| 1 | **WAL幽灵 2M轮转** | `modules/wal.py DEFAULT_MAX_BYTES=2*1024*1024` + `_wal_lock` 串行化 `append/mark_complete/cleanup` + `api_server.periodic_flush` 每日 `wal.cleanup()` + `/api/cleanup` 轮转 | `wal.jsonl 453K/2M`，`pending真待0`，`wal.jsonl.bak-20260820 839K` 归档 |
| 2 | **Coalesce留尾300** | `modules/coalesce.py PROFILES` 三档 `tail_chars 300 head_chars 200` + `_smart_trim(head 200+...省略+tail 300)` + `coalesce_trim` 日志 | `tech` 1815→513 含尾，`default/intimate` 未超限原样，结论不丢 |
| 3 | **secret零衰减** | `modules/decay.py "secret":{"multiplier":0.0}` `get_score` 锁 `1.0` | `bzssn1997` 类永不衰减 |
| 4 | **门控口令白名单** | `modules/memory_gate.py EXPLICIT_SEARCH_PATTERNS` 追加 `.*(搜一下|查一下|回忆一下).*` + `GATE_PASS_PHRASES` 锚行首 + `_pass_phrase_re` | `test_gate_passphrase.py ALL PASS`，`搜一下 DNS污染` 放行 |
| 5 | **AutoDream日/周** | `api_server.periodic_flush` `AUTODREAM_DAILY 24h days=1` + `WEEKLY 7d days=7` + `_rebuild_vectors` | `health` 五探针绿，`AutoDream daily triggered` 日志 |
| 6 | **每日宿主备份** | `baize/scripts/sync_to_host.sh`：`sqlite3 .backup` 热备 → `rsync` 双份 `facts_YYYYMMDD.db`+`facts_latest.db`+`wal_YYYYMMDD.jsonl` 到宿主 `记忆备份`，30天滚动 `find -mtime +30 -delete`；`systemd baize-backup.service` + `baize-backup.timer OnCalendar=03:00 Persistent=true RandomizedDelaySec=300` | 首备 `162M md5 d98ff...` 双份一致 `23391` 条，`systemctl --user list-timers` 13h 后触发，`PRAGMA integrity_check ok` 还原演练通过 |

### 4.19 轻量化补丁（2026-08-20 实施，101M→73M）

| 项 | 改动 | 收益 | 风险 |
|---|---|---|---|
| **孤儿向量清零** | `POST /api/cleanup` 清 `memory_vec`/`memory_vec_i8` 中 `superseded` 孤儿 `931→0`（后又 `30→0`） | `4.5M` | 零风险，查询侧已先排除，清理仅回收存储 |
| **LRU 512→256** | `modules/hybrid_recall.py _embed_cache_max 512→256`（TTL 3600 保留，`_embed_lock` 保护）| `2-3M` | 同查询命中率微降，冷查询多一次 bge-m3 调用 |

实测：重启前 `101M peak134M` → 重启后 `73.1M peak89.5M`（`RSS 102M`），`active 12790` 全有向量 `orphan 0`，三轮检索回归全过。


### 4.20 Voyage双引擎上线（2026-08-26 实施，双保险主备）

**背景**：bge-m3（SiliconFlow 免费）中文强但英文检索略弱、8K 上下文、裸绣不分 query/document，短词如“飞牛”在 FTS trigram MATCH 0 时易沉底。Voyage 4-lite 为闭源调教款：32K 上下文、input_type 不对称（query 尖/document 厚）、MTEB/BEIR 压 bge 一档；免费额度**200M 终身/号**（与 rerank 池分开计，Batch API 不扣池），绑卡解锁 2000 RPM/16M TPM，不绑仅 3 RPM。

| 项 | 选型 | 免费额度 | 超后单价 | 限速 | 备注 |
|---|---|---|---|---|---|
| Embedding 主用 | Voyage voyage-4-lite 1024维 | 200M 终身 | $0.02/M | 绑卡后 2000 RPM / 16M TPM | 实测单条 543ms p50 556ms，批量 16条 12.4 tok/条 |
| Embedding 兜底 | bge-m3 (SiliconFlow) | 无限免费 | $0 | ~100-200 RPM | 双保险，Voyage 429/无 key 自动滑回 |
| Rerank 主用 | Voyage rerank-2.5-lite 32K | 200M 终身 | $0.02/M | 同池 | 5 docs 585ms / 20 docs 829ms |
| Rerank 兜底 | bge-reranker-v2-m3 | 无限免费 | $0 | 同上 | 无缝回退 |
| LLM | Ling-3.0-flash (蚂蚁百灵) | 免费 | $0 | - | 事实抽取 + AutoDream 蒸馏，两处唯一 LLM 调用点 |

**实现三刀**（`modules/hybrid_recall.py` + `modules/reranker.py` + `api_server.py`）：
- `VOYAGE_URL/VOYAGE_MODEL/VOYAGE_KEY_PATH` + `BGE_URL/BGE_MODEL` 双配置；`BAIZE_VOYAGE_KEY` 环境变量优先、`.voyage_key` 兜底，`BAIZE_EMBED_KEY` 保留 bge 兜底
- `_get_embedding(text, input_type)` 区分 `query` vs `document`，缓存 key 带 `input_type:` 前缀；`_fetch_embedding` 封装 Voyage(input_type) 与 bge(无) 双路径，Voyage 主调、失败/无 key 滑回 bge
- `reranker.py` 抽 `_call_rerank()` 兼容 Voyage `{data:[{relevance_score,index}]}` 与 bge `{results}` 双格式；`rerank()` 先 Voyage 后 bge，LRU 100/300s 保留
- 存库 `store_vector` → `document` 厚衣；搜库 `_vector_search_i8/_f32` → `query` 尖衣；全量重烙脚本 `scripts/voyage_reembed_all.py`：BATCH 16→32、sleep 0.4s、Retry-After 退避、vec0 `DELETE+INSERT`（virtual table 不支持 REPLACE）、幂等续跑

**全量重烙战报（2026-08-26 实测，YOU数字卡绑后解锁）**：
- 总活 16,535 条 → 首轮 16,375 成 + 160 败（`database is locked` 1批 + 解锁前 3 RPM 尾巴），耗时 980s（16分）+ 补齐 160/160 2分，零 429
- 耗 0.8M tokens = 200M 的 0.4%，够烙 250 遍；日增 ~1,370 条/天 ≈22K/天 → Embed 撑 25 年、Rerank 撑 130 年
- 图上 `voyage-4-lite 284K/199.7M 0.14%` + `rerank-2.5-lite 12K/199.9M 0.01%` 与官价 `docs.voyageai.com/docs/pricing` 分池一致

**blind 盲测（query/document 分衣实效，8-26 真库）**：
- 单针余弦同一对 `飞牛`：穿错 0.267 → 穿对 0.376 涨 40%
- 端到端 Hybrid Top5：`搜 飞牛` 穿错 1/5 含飞牛（Top 0.816 虚高但全偏）→ 穿对 5/5 含飞牛（0.724/0.750/0.778），`搜 9router` 穿对首条 0.984 hybrid；短词 `日志/部署/WAL/AutoDream/bge-m3` 均从 0-2/5 救回 4-5/5
- Round2 清污染后（排除 8-26 当日聊天）：8 词中 7 词 query 区分度优于 doc，`日志/部署/AutoDream` doc 区分度为负（把负例也抱进来了）

**降级与运维**：
- `VOYAGE 429/限速/无 key` → 静默回退 bge，不阻检索；`health` 5 探针全绿，`HybridRecall keys: voyage=set bge=set` / `Reranker keys: voyage=set bge=set`
- `POST /search` 仍走 `vector 0.5 + FTS 0.3 + graph 0.2 → rerank-2.5-lite` 全链路；Ling 蒸馏（AutoDream）不动，Voyage 只管鼻子/舌头
- 宿主 `Payment methods` 已绑中行长城万事达 YOU 数字信用卡（公司统一办的个人卡，Mastercard 网络，Stripe 3D 验证通过），`Budget limits` 建议拧 $5 防夜扣

---

## 五、资源消耗

### 5.1 运行时

| 指标 | 数值 |
|------|:---:|
| 磁盘占用 | **227 MB VM / 199 MB 宿主**（facts.db，2026-08-26 实测，VM 227M 含 int8 双写，宿主 `facts_latest.db` 199M 同步；08-20 162M；08-05 40.3MB） |
| CPU 空闲 | < 1% |
| 启动时间 | < 3 秒（**v1.2 D1 注意**：若存在 WAL pending，启动含重放阶段；8-3 实测重放 218 条成功；可用 `BAIZE_WAL_REPLAY=0` 跳过） |
| 内存占用 | **~73-127 MB**（2026-08-26 实测，`systemd` 常驻 73-127M peak 89-143M，Voyage 双引擎 + LRU 256 + 孤儿清零后；08-20 73M；重启前 101M peak134M；Linux 三刀 trim：30min gc+malloc_trim / 2000 分块 / 500 分批） |

### 5.2 API 延迟（实测）

| 端点 | 延迟 | 说明 |
|------|------|------|
| `/health` | ~30ms | 含 5 个探针（db/vss/embedding/rerank/llm，embedding 30s 缓存） |
| `/search`（无 rerank） | ~50ms | 闸门过滤后直接返回 |
| `/search`（含 rerank，冷） | ~350ms | 含 Cross-Encoder 实时重排 |
| `/search`（含 rerank，embedding 缓存命中） | **~42ms** | v1.1 实测，同查询提速 91% |
| `/add`（异步） | < 10ms | 潮浪并批，异步写入 |
| `/add`（同步 force_sync） | < 15s | v1.1 LLM 超时收紧后最坏 15s |
| int8 向量检索（2500 条量级） | **17.7 ms** | v1.1 P1-1 实测（float32 路径 18.6ms） |
| `/api/auto-dream` | < 10ms | 异步执行，返回 job_id |
| `/api/cleanup` | ~秒级 | v1.1 新增，全量扫描标记 |

### 5.3 模型依赖

| 模型 | 用途 | 来源 | 价格 |
|------|------|------|:---:|
| Voyage voyage-4-lite | Embedding 主用（1024维 32K，query/document 分衣） | Voyage AI | 🆓 200M 终身免费 / $0.02/M |
| BAAI/bge-m3 | Embedding 兜底（1024维 8K） | 硅基流动 | 🆓 免费（双保险） |
| Voyage rerank-2.5-lite | Rerank 主用（32K） | Voyage AI | 🆓 200M 终身免费 / $0.02/M |
| BAAI/bge-reranker-v2-m3 | Rerank 兜底 | 硅基流动 | 🆓 免费（双保险） |
| Ling-3.0-flash | LLM（事实抽取、蒸馏、WAL 重放，两处唯一调用点） | 蚂蚁百灵 api.ant-ling.com | 🆓 免费 |
| **总计** | | | **¥0 白嫖（Voyage 200M 够 25 年）** |

### 5.4 代码规模（v1.2 实测）

| 类别 | 数量 |
|------|:---:|
| Python 模块 | 15（服务端，v1.2 quantize.py + v1.4 voyage 双引擎 reranker 重构 + voyage_reembed_all.py） |
| 核心代码行 | **~4,139**（api_server 1,289 + modules 2,850，2026-08-26 实测；v1.3 约 3,600） |
| 核心 API 端点 | **18**（+ Voyage 双引擎内部重构，不新增端点） |
| 后台线程 | 1（periodic_flush，30min trim + AutoDream 日/周） |
| 外部调度 | Hermes cron：白泽周维护（周日 03:15）+ 每日宿主备份 03:00 |
| Provider 插件 | plugins/baize/__init__.py（含 on_pre_compress 压缩桥 + L1 缓存友好） |

---

## 六、核心模块清单

```
baize/
├── api_server.py             # FastAPI 主服务（端口 8767，v1.2.0）
├── config.json               # 配置文件（LLM/向量库/潮浪 profile）
├── modules/
│   ├── __init__.py           # 模块导出
│   ├── memory_gate.py        # 相关性闸门 + 纠正信号 + 问句 + 短确认 + 口令白名单
│   ├── fastpath.py           # 快速通道（正则提取，第三人称）
│   ├── coalesce.py           # 潮浪并批（留尾 300，新版）
│   ├── decay.py              # 9轨道 Ebbinghaus 衰减（含 secret 零衰减）
│   ├── hybrid_recall.py      # 混合检索 + Voyage 4-lite 主/bge-m3 兜底 + input_type 分衣 + LRU 256/3600s + find_duplicate + int8/f32 双检索
│   ├── llm_extract.py        # LLM 事实抽取（Ling-3.0-flash 15s 超时，两处唯一 LLM 点之一）
│   ├── evolution.py          # 知识演化追踪（4种关系，v1.2 user_id 隔离 + 批量 superseded）
│   ├── wal.py                # WAL 预写日志（2M 轮转 + _wal_lock 串行化 + 真重放）
│   ├── core_memory.py        # CoreMemory 3-block
│   ├── auto_dream.py         # AutoDream 蒸馏（二道 LLM 蒸馏，20条/批，73% 成功 Jaccard 兜底）
│   ├── quantize.py           # 量化公共函数（v1.2 新增）
│   └── reranker.py           # Voyage rerank-2.5-lite 主/bge 兜底 + 双格式兼容 + LRU 100/300s
├── data/
│   ├── facts.db              # SQLite 数据库（记忆 + FTS5 + 向量 + WAL）
│   └── wal.jsonl             # WAL 预写日志（v1.2：pending 可重放）
├── workspace/
│   └── default/              # 工作区（Checkpoint 预留）
├── logs/
│   ├── api_server.log        # 服务日志（WAL 重放/校验/隔离事件均记录）
│   ├── stdout.log            # 标准输出（HTTP 访问日志）
│   └── stderr.log            # 错误日志
├── scripts/
│   ├── verify_*.py           # 各批次验证脚本（A/D/B+/C + Voyage 盲测）
│   ├── migrate_int8.py       # int8 迁移（v1.2：流式 fetchmany + 公共 quantize）
│   ├── voyage_reembed_all.py # Voyage 全量重烙（BATCH 32/0.4s + Retry-After + vec0 DELETE+INSERT）
│   └── ...
├── backup-review-0803/       # v1.2 修复前代码备份（可回滚）
├── .voyage_key               # Voyage API Key（voyage-4-lite + rerank-2.5-lite，0600，主用）
├── .embed_key                # 硅基流动 API Key（bge-m3 + rerank，兜底；Linux 已迁环境变量 BAIZE_VOYAGE_KEY/BAIZE_EMBED_KEY）
├── .llm_key                  # 蚂蚁百灵 API Key（Ling-3.0-flash，两处唯一 LLM 点）
├── scripts/sync_to_host.sh   # 每日宿主热备（2026-08-20 新增，sqlite .backup + rsync 双份）
└── start_service.bat         # Windows 启动脚本（历史，Linux 用 systemd baize.service）

Hermes 侧：
├── plugins/baize/__init__.py # MemoryProvider 插件（分类修复/prefetch 覆盖/CoreMemory 缓存）
└── scripts/baize_maintenance.py  # 周维护脚本（蒸馏 + 清理 + WAL 轮转，.py 版）
```

---

## 七、部署指南

### 7.1 环境要求

- Python 3.11+
- SQLite 3.35+（chroma 后端要求；白泽原生使用 sqlite-vec，需支持扩展加载）
- 8 GB RAM（实测仅需 ~93 MB）
- ≥ 10 GB 磁盘（facts.db 实测约 74MB；P5 备份 90 天滚动按当前量级 ≈ 7GB，预留余量）

### 7.2 快速启动

**Linux（当前主用，Debian 13，VM 192.168.1.100）**
```bash
cd /root/.hermes/baize
/usr/bin/python3 api_server.py  # 或 systemctl --user start baize
```
**Windows（历史，DELL 老家）**
```bash
cd E:/AI工具/Hermes/baize
E:/AI工具/Hermes/venv/Scripts/python.exe api_server.py
```

服务默认监听 `http://127.0.0.1:8767`。
**部署硬约束：禁止将监听地址改为 `0.0.0.0` 或局域网 IP**——鉴权驳回（见 §4.15）依赖"所有访问者均在本机"这一前提；如确需跨机访问，必须先实现 API Token 鉴权（见 §4.15 v2.0 方向）再改监听。

### 7.3 开机自启

**Linux（当前主用，systemd --user）**
```ini
# ~/.config/systemd/user/baize.service
[Service]
Type=simple
WorkingDirectory=/root/.hermes/baize
Environment="BAIZE_EMBED_KEY=sk-..."
Environment="BAIZE_LLM_KEY=sk-..."
ExecStart=/usr/bin/python3 /root/.hermes/baize/api_server.py
Restart=always
RestartSec=5
```
```bash
export XDG_RUNTIME_DIR=/run/user/0; export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/0/bus
systemctl --user daemon-reload && systemctl --user enable --now baize.service
systemctl --user status baize # Memory: 73M peak89M
# 改 key：改 baize.service Environment 行 → daemon-reload → restart baize
```
- `loginctl enable-linger root` 开机自启，无需登录即起
- 睡眠/休眠：systemd 用户服务不受空闲杀进程影响

**Windows（历史，NSSM）**
```powershell
& "E:\AI工具\nssm.exe" status baize
& "E:\AI工具\nssm.exe" restart baize  # 需管理员
```
`SERVICE_AUTO_START` + `AppRestartDelay 5000`；飞书端 no_agent cron 以 SYSTEM 权限 `nssm restart baize` 为免 UAC 通道（历史）。

**每日宿主备份（2026-08-20 新增）**
```ini
# ~/.config/systemd/user/baize-backup.service + baize-backup.timer
OnCalendar=03:00 Persistent=true RandomizedDelaySec=300
ExecStart=/bin/bash /root/.hermes/baize/scripts/sync_to_host.sh
# 热备：sqlite3 .backup → rsync 双份 facts_YYYYMMDD.db + facts_latest.db + wal_YYYYMMDD.jsonl → /data/backup/baize 30天滚动
```

### 7.4 定期维护（v1.1 起，v1.2 更新）

**Hermes 定时任务「白泽周维护」**（job_id `94e263b2e019`，每周日 03:15，no_agent 脚本）：

```bash
# E:/AI工具/Hermes/scripts/baize_maintenance.py
# 1. POST /api/auto-dream?days=7   蒸馏去重（LLM 输出校验 + 向量重建）
# 2. POST /api/cleanup             衰减归档 + 孤儿向量清理（含 int8）+ WAL 轮转
```

与「Memory自动压缩」（周日 03:00）错开 15 分钟，避免竞争 LLM 配额。

**v1.2 新增监控体系**（详见第十四章）：系统健康哨兵（每 6 小时，零 token）+ state.db 触发器守卫（每日）+ 补丁哨兵（每日）。

### 7.5 验证

```bash
curl http://127.0.0.1:8767/health
# {"status":"ok","service":"白泽 (Bai Ze)","version":"1.3.1-baize","probes":{"db":true,"vss":true,"embedding_api":true,"rerank_api":true,"llm_api":true},"degraded":[]}

curl http://127.0.0.1:8767/api/memory/health
# {"status":"ok","version":"1.3.1-baize","report":{...}}
```

**⚠️ v1.2 重启后验证注意**：若存在 WAL pending，服务启动后先执行重放（208 条实测 ~24 分钟），期间端口不监听、health 返回 10061——**这是正常启动过程，不是故障**。重放完成标志（api_server.log）：`WAL replay done: replayed=208, already_present=0, failed=0, skipped=0` + `Application startup complete`。验证重启是否成功看 `netstat -ano | grep 8767` 的 PID 变化。

---

## 八、与 AI Agent 集成

白泽设计为 **Hermes Agent** 的原生思想引擎，通过 `MemoryProvider` 插件实现三级上下文注入：

```
Hermes 每轮对话前
  → MemoryProvider.prefetch()
    → CoreMemory 注入（60s 缓存，v1.1）
    → 白泽 /search 检索（语义相关记忆 + Cross-Encoder Rerank）
    → 合并注入到 Hermes 上下文

Hermes 每轮对话后
  → MemoryProvider.sync_turn()
    → 内容分类（v1.1：仅用户消息，防误杀）
    → LLM 提取事实（Ling-3.0-flash，15s 超时）
    → 异步写入白泽（coalesce 潮浪并批 + v1.2 批内文本预筛）
    → 写入去重（v1.2：embedding 去重 + superseded 排除）
    → 知识演化检测（v1.2：user_id 隔离）
```

### 8.1 Provider 插件配置

**Hermes config.yaml 配置**：
```yaml
memory:
  provider: baize
```

**环境变量**（可选）：
```bash
BAIZE_URL=http://127.0.0.1:8767    # 白泽服务地址（默认）
BAIZE_USER_ID=default               # 用户 ID（默认）
```

### 8.2 Provider 插件实现

白泽的 Provider 插件位于 `E:/AI工具/Hermes/plugins/baize/__init__.py`（注意：插件扫描目录为 `$HERMES_HOME/plugins/<name>/` 一级子目录，`plugins/memory/baize/` 是无效路径），类名 `BaiZeProvider`。

**插件能力**：
- 分类修复：只判断用户消息，临时观察正则锚定
- prefetch 覆盖：`_pending_query` 接力，避免陈旧上下文注入
- CoreMemory 缓存：60s TTL，减少每轮 HTTP 请求
- 暴露 `baize_search` / `baize_add` 工具（模型可主动检索/写入）

### 8.3 与其他 Agent 集成

对 Claude Code 等外部 Agent（**均在本机运行**，无跨机访问场景），提供标准 REST API + 命令行工具：
> 注：若未来出现跨机接入需求，按 §4.15 v2.0 方向先实现 API Token 鉴权。

```bash
python shared_memory/search-cli.py "关键词"        # 搜索
python shared_memory/search-cli.py --health       # 健康检查
python shared_memory/search-cli.py --add "标题" "摘要"  # 写入
```

任何支持 HTTP 钩子的 Agent 系统均可通过 `/add`、`/search` 端点接入。**v1.2 起** `/api/auto-dream`、`/api/consolidate/session` 端点支持 `user_id` 参数，多用户场景可直接透传。

---

## 九、Token 消耗分析

### 9.1 每轮对话消耗

| 项目 | Token 数 |
|------|---------|
| CoreMemory 注入 | ~200 |
| 检索结果注入（3-5条） | ~300 |
| Rerank 调用 | ~1,200 |
| **单轮总计** | **~500-1,700** |

### 9.2 定时任务消耗

| 任务 | 频率 | Token 数 | 费用 |
|------|------|---------|------|
| AutoDream 蒸馏 | 每周1次（周日 03:15） | ~26,000 | ¥0 |
| /api/cleanup 清理 | 每周1次（与蒸馏同批） | 0（无 LLM） | ¥0 |
| **月度总计** | | ~110,000 | **¥0** |

**v1.2 优化**：WAL 重放 208 条（一次性）走 LLM 提取，消耗约 5-10 万 token（一次性成本）；`BAIZE_WAL_REPLAY=0` 可跳过。去重批量化后写入侧 embedding API 调用减半。

### 9.3 与原生 Memory 对比

| 指标 | 原生 Memory | 白泽 v1.3 |
|------|------------|----------|
| 每轮注入 | ~750 tokens | ~200 tokens |
| 每天注入（50轮） | 37,500 tokens | 10,000 tokens |
| 每月节省 | - | **825,000 tokens** |
| 等价费用（MiMo Pro） | - | ~¥40-80/月 |
| **白泽运行成本** | - | **¥0** |

**v1.3.1 更新**：上下文治理后（L1 缓存友好 + L2 阈值 40% + 系统提示瘦身），每轮注入块稳定（缓存命中价 ≈ 1/10）、上下文水位 45K → 38K、system prompt 减 ~25%——三项叠加后每轮输入成本进一步下降约 30-40%。

---

## 十、设计哲学

```
"记忆不是堆积，而是筛选。"        — Ebbinghaus 遗忘曲线
"遗忘不是缺陷，而是智慧。"        — 分轨衰减设计
"思想不是存储，而是编织。"        — Cross-Encoder Rerank
"全栈免费，功能完整。"            — 白泽核心理念
"数据不因崩溃而丢，不因隔离而串，不因幻觉而错。"  — v1.2 玄武
```

白泽的每一次版本升级，都在回答同一个问题：**AI 应该怎样记忆？**

v1.0 白泽给出的答案是：记忆不只是筛选和遗忘——**记忆是编织**。把散落的线索捻成线，把相似的线纺成束，在需要的时候，把最精准的那根线递给 Agent。

v1.1 精卫的回答是：编织之前，先要**织对**——记下真正该记的（修复误杀）、不织重复的线（写入去重）、定期梳理线团（蒸馏治理）、理清归档的角落（WAL 轮转与全量改名）。

v1.2 玄武的回答是：织好之后，还要**织得牢**——如同玄武龟蛇镇守四方：**崩溃时不丢线**（WAL 真重放）、**不同人的线不串**（跨用户隔离）、**机器说胡话时不乱剪**（LLM 输出校验）、**线团打分不虚高**（打分校正）。让记忆的每一根线都经得起时间与意外的考验。

---

## 十一、降级策略

| 依赖 | 故障场景 | 降级方案 | 影响 |
|------|---------|---------|------|
| Voyage voyage-4-lite（Embedding 主） | Voyage API 429/不可用 | 自动滑回 bge-m3 兜底（静默回退，LRU 缓存续命） | 语义仍可用，32K→8K 上下文略降 |
| bge-m3（Embedding 兜底） | 硅基流动 API 不可用 | 退化为纯 FTS5 全文检索（缓存命中可缓解） | 语义匹配丧失，仅关键词匹配 |
| Voyage rerank-2.5-lite（Rerank 主） | Voyage API 429/不可用 | 自动滑回 bge-reranker-v2-m3 | 精度微降，仍重排 |
| bge-reranker-v2-m3（Rerank 兜底） | 硅基流动 API 不可用 | 跳过 Rerank，直接返回原始排序 | 精度下降，但检索仍可用 |
| Ling-3.0-flash（LLM） | 蚂蚁百灵 API 不可用 | AutoDream fallback 到 Jaccard 规则引擎 | 蒸馏质量下降，但去重仍可用 |
| 写入去重（v1.1） | 向量检索异常 | `find_duplicate` 抛异常被捕获，跳过去重继续写入 | 去重失效，但写入不受影响 |
| LLM 抽取超时（v1.1） | 抽取 15s 超时 | fallback 存原始文本 | 记忆为原文，无 LLM 提炼 |
| **WAL 重放（v1.2）** | **重放需逐条 LLM 提取，启动慢** | **`BAIZE_WAL_REPLAY=0` 降级为仅审计** | **pending 不重放，启动秒回** |
| **int8 向量表（v1.2）** | **int8 查询异常** | **`_vector_search` 捕获后回退 float32** | **降级路径保留，兼容** |

**降级原则**：任何单点故障不会导致系统崩溃，只影响对应功能的质量。

---

## 十二、AutoDream Jaccard 阈值

| 阈值 | 用途 | 说明 |
|------|------|------|
| > 0.9 | 标记重复（superseded） | 几乎完全相同的记忆 |
| 0.7 - 0.9 | 存入 merge_suggestions 待人工审核 | 高度相似但不完全相同 |
| < 0.7 | 不处理 | 差异较大，保留两条 |

**补充（v1.1）**：写入侧去重使用**向量距离**（阈值 0.05，等价相似度 0.975），与蒸馏侧 Jaccard 阈值（0.9）互为补充。

**补充（v1.2）**：
- consolidation 参数全部钳制：`dup_threshold=clamp(v,0,1)`、`cand_threshold=clamp(v,0,dup)`、`minutes=max(1,·)`——传负值不再能整窗互相 supersede
- 窗口 Jaccard 计算改 bigram 倒排剪枝（不共享 bigram 的对直接跳过，O(n²) → 近似线性）
- 合并/标记结果均经 LLM 输出校验（D2）与归属校验（D3）

---

## 十三、命名规范

系统名称统一为**白泽（Bai Ze）**，技术标识为 **baize**：

| 层面 | 规范 |
|------|------|
| 服务名 | `baize`（Windows NSSM / Linux systemd `baize.service`） |
| 目录名 | `E:/AI工具/Hermes/baize/`（Windows老家） / `/root/.hermes/baize`（Linux VM当前） |
| 插件目录 | `$HERMES_HOME/plugins/baize/` |
| 环境变量 | `BAIZE_URL` / `BAIZE_USER_ID` |
| API 返回 | `service: "白泽 (Bai Ze)"`，`version: "1.3.1-baize"` |
| 定时任务 | 白泽周维护（job_id `94e263b2e019`） |
| 运维技能 | `baize-memory-system`（devops 分类） |
| 历史旧名 | duMem / dumem —— v1.1 已全量清除，仅历史归档文档中保留 |

---

## 十四、可靠性与监控

### 14.1 健康检查端点

| 端点 | 说明 | 返回信息 |
|------|------|---------|
| `/health` | 服务存活 + API 连通性 | 状态、版本、模块状态、5个探针、degraded 列表 |
| `/api/memory/health` | 记忆系统健康报告 | 记忆数、轨道分布、7天增长、演化关系 |
| `/api/rerank/status` | Reranker 状态 | 模型、API、Key 配置 |
| `/api/core-memory` | CoreMemory 状态 | 3个 block 内容和更新时间 |
| `/api/cleanup` | 手动触发清理 | 归档数、WAL 轮转数 |
| `/add/coalesce/stats` | 潮浪统计 | 波次、消息数、LLM 节省率 |

**/health 探针详情**：

| 探针 | 检测方式 | 降级行为 |
|------|---------|---------|
| db | SQLite 文件存在性 | 文件不存在则 degraded |
| vss | sqlite-vec 模块加载状态 | 未加载则 degraded |
| embedding_api | 实际调用 Voyage 4-lite 主 + bge-m3 兜底（30秒缓存） | 双引擎失败则 degraded，退化为 FTS5 |
| rerank_api | 检查 Voyage/bge reranker key 是否配置 | 均未配置则跳过 Rerank |
| llm_api | 检查 llm_key 是否配置 | 未配置则 AutoDream fallback 到规则引擎 |

### 14.2 失败可见性

| 场景 | 可见性机制 |
|------|-----------|
| LLM 调用失败 | 日志 WARNING + fallback 到规则引擎 |
| Rerank 调用失败 | 日志 WARNING + 返回原始排序 |
| Embedding 调用失败 | 日志 WARNING + fallback 到 FTS5 |
| 写入去重失败 | 日志 WARNING + 跳过去重继续写入 |
| **WAL 重放单条失败（v1.2）** | **日志 WARNING + 该条跳过不阻塞启动** |
| **LLM 输出非法 ID（v1.2）** | **日志 WARNING + 丢弃非法项** |
| **跨用户归属不符（v1.2）** | **日志 WARNING + 拒绝写入** |
| 事实写入失败 | WAL 预写日志保护，重启后自动重放 |

### 14.3 日志文件

```
# Linux 当前
/root/.hermes/baize/logs/api_server.log
/root/.hermes/baize/logs/backup.log  # 每日宿主备份日志（2026-08-20 新增）
# Windows 历史
E:/AI工具/Hermes/baize/logs/api_server.log
```

日志级别：INFO（正常操作）、WARNING（降级运行/校验拦截）、ERROR（功能失败）。WAL 日志每周自动轮转（保留 7 天）。**v1.2 关键日志标记**：`WAL replay done`、`Dedup skip`、`not owned by user`、`invalid id discarded`。

### 14.4 自动化监控（Hermes cron 体系，v1.2 更新）

| 任务 | 频率 | 模式 | 作用 |
|------|------|:---:|------|
| 白泽周维护 | 周日 03:15 | 脚本 | 蒸馏 + 清理 + WAL 轮转（零 token）|
| **系统健康哨兵** | **每 6 小时** | **脚本** | **磁盘/白泽/gateway/state.db 四查，异常才告警（零 token）** |
| **state.db 触发器守卫** | **每日 08:15** | **脚本** | **触发器瘦身 + 大小 + 索引完整性（零 token）** |
| 补丁哨兵 | 每日 08:10 | agent | 白泽插件完整性 + memory.provider 配置 |
| 记忆周报 | 周一 09:30 | agent | 水位 + 白泽状态周报 |

**v1.2 说明**：原「数据库体检」「系统健康检查」两个 agent 任务（每天 8 次 LLM 调用）已合并为「系统健康哨兵」no_agent 脚本（零 token、异常才推送），每月节省约 170 万 token。

---

## 十五、代码规模说明

白泽 ~3,600 行核心代码实现 20+ 项功能，压缩比约为同类项目的 1/5。原因：

| 因素 | 说明 |
|------|------|
| **SQLite 一体化** | 向量（sqlite-vec + Voyage/bge 双引擎）、全文（FTS5）、结构化数据共用一个数据库，无需多引擎协调 |
| **模块复用** | decay.py 同时服务于检索衰减和 AutoDream 清理；quantize.py 双写/迁移共用 |
| **简化实现** | 9轨道衰减是 if-else + exp() 公式（decay.py 仅 85 行），非状态机 |
| **外部依赖轻量** | Rerank(Voyage/bge)、Embedding(Voyage/bge)、LLM(Ling) 均 REST API 委托，不内嵌模型 |
| **无冗余抽象** | 不过度设计，每个模块直接解决问题 |
| **FTS5 trigram 分词** | 使用 trigram 分词而非真正中文分词（如 jieba），简化实现 |

**代码统计**（2026-08-26 实测）：

| 范围 | 行数 |
|------|------|
| api_server.py | 1,289（v1.3 1,006 + Voyage 双引擎 + 备份/trim） |
| modules/（13 个文件，含 quantize.py + Voyage 双引擎） | 2,850（v1.3 2,593 + Voyage 重构） |
| scripts/（含 voyage_reembed_all.py 等） | 新增全量重烙脚本 |
| **核心代码合计** | **~4,139** |
| Provider 插件（plugins/baize/__init__.py） | ~560 |

**对比参考**：aiduMEM v10.1 约 15,000 行 / 51 模块，白泽约 3,600 行 / 13 模块。白泽用 1/5 的代码实现了可审计、可验证的同等核心能力。

---

## 十六、性能实测记录（v1.2）

| 指标 | v1.1 基线 | v1.2 实测 | 提升 |
|------|----------|----------|------|
| 搜索延迟（同查询，缓存命中） | 42ms | 42ms | 持平（缓存保底）|
| FTS 打分 | 最优恒 1.0（弱匹配虚高） | 强 0.333 vs 弱 0.038 | **区分度质变** |
| importance 权重 | 计 3 次（叠加放大） | 计 1 次（decay 统一） | **语义校正** |
| 图谱扩展 | 绕过 age 衰减（陈旧记忆被抬升） | 补乘 decay（400 天前 ≈0.000） | **时序校正** |
| 检索连接数 | O(节点数)（最多 ~48 连接/查询） | O(调用数)（批量 IN） | **数量级下降** |
| 去重 embedding 调用 | 2N 次/多 fact 消息 | ~N 次（批内文本预筛） | **50% 成本下降** |
| WAL 崩溃恢复 | 只读不重放（崩溃即丢） | 启动自动重放（208 条 0 失败） | **从无到有** |
| 跨用户安全 | 无隔离（可串数据） | 全链路 user_id + 归属校验 | **从无到有** |
| LLM 输出安全 | 幻觉 ID 直接执行 | 批内校验 + rowcount 检查 | **从无到有** |
| 验证断言 | 单批 | **38 项留存断言全过**（D12+B+11+C15，可复现） | **可审计** |

---

## 十七、源码审核记录

### v1.0 审核（GLM 5.2 四轮，2026-07-28）

| 轮次 | 审核方 | 发现问题 | 修复数 | 状态 |
|------|--------|---------|--------|------|
| 首轮 | GLM 5.2 | 9 项 | 7 项 | ✅ |
| 第二轮 | GLM 5.2 | 2 项 | 2 项 | ✅ |
| 第三轮 | GLM 5.2 | 2 项 | 2 项 | ✅ |
| 第四轮 | GLM 5.2 | 4 项 | 4 项 | ✅ |
| **累计** | | **11 项可修复** | **11 项** | **✅ 全部修复** |

### v1.1 优化（Claude Code 实施 + Hermes Agent 实测验证，2026-07-31）

9 项优化全部实施并验证（P0 误杀修复/治理机制、P1 缓存×3、P2 去重/实例复用、全量改名），均有 `.bak-0731` 备份可回滚。

### v1.2 内核加固（opencode 执行 + 独立验证，2026-08-03）

**两轮独立深度审查**：
- **Claude Code 首轮**（只读审查）：发现 2 高危 + 8 中危（int8 双写不一致、清理不清 int8、连接风暴、FTS min-max 虚高、importance 三重复计、图谱绕过 decay、参数钳制等）→ 批次 A + B+ + C
- **opencode 二轮**（只读审查）：发现首轮漏掉的 **3 个高危**（WAL 重放失效、跨用户隔离缺失、LLM 输出未校验）+ 中危（合并后向量不重建、去重逐条 embedding 等）→ 批次 D

**四批修复（24 项，38 条留存断言全过）**：

| 批次 | 内容 | 验证 |
|------|------|------|
| A | 高危 5 项：双写一致性、清理清 int8、905 条残留清零、int8 检索优化、迁移脚本 | ✅ verify_a_consistency.py（mode=ro 三查）|
| D | 新高危 3 项：WAL 真重放、LLM 输出校验、跨用户隔离 | ✅ 12 断言（verify_baize_D.py，留存可复现）|
| B+ | 性能 8 项：连接风暴、向量重建、去重批量化、缓存线程安全、superseded 排除、quantize、流式迁移、jobs TTL | ✅ 11 断言（verify_baize_B.py，留存可复现）|
| C | 打分 8 项：FTS 打分、importance、图谱 decay、参数钳制、Jaccard 剪枝、API 错误处理、schema 统一、批量查重 | ✅ 15 断言（verify_baize_C.py，留存可复现）|

**验证原则**：py_compile 全过 + 临时库实例化测试（零写真实库）+ mode=ro 只读验证；**服务重启后实测 WAL 重放 208 条成功**（新代码首次运行即验证 D1）。

---

## 十八、后续优化路线

| 优先级 | 特性 | 说明 |
|--------|------|------|
| ⭐ | WAL pending 二次分析 | 实测仍有历史 pending 未重放（如 226 条未在 DB 中的记录），评估重放策略或归档 |
| ⭐ | evolution 候选池优化 | 当前每次写入扫描最近 500 条做 Jaccard，数据 >5,000 条时需加索引/预筛 |
| ⭐ | 受控索引边界 | 当需要多文档索引时，添加白名单/黑名单机制 |
| ✅ | 压缩备份插件（压缩桥） | 上下文压缩前自动提炼重要信息 —— **v1.3.1 已实施**（on_pre_compress + /api/ingest，实测归档 18 条） |
| ⭐ | 教训三态治理 | 待验证/已闭环/未内化 |
| ⭐ | 增量索引 + SHA-256 | 当数据量增长到数万条时 |
| 🟢 | 中文分词替代 trigram | wangfenjin/simple 类 tokenizer 可显著降低 FTS 索引膨胀（需 Hermes 内核支持，等待官方）|
| ✅ | Voyage AI 双引擎 | **已完成 2026-08-26**：voyage-4-lite + rerank-2.5-lite 主用 + bge 双兜底 + input_type 分衣 + 全量重烙 16,535 条，见 §4.20 |

---

> 📄 本文档为白泽 v1.4-BaiZe "陆吾" 技术白皮书
> 所有信息已脱敏处理，可公开分享
> 2026-08-10 / 2026-08-20 增补（Linux化 + 六刀 + 轻量化） / 2026-08-26 增补（Voyage双引擎 + 盲测 + 200M白嫖核算）
