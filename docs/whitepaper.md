# 📜 白泽 v1.5.1 "天禄·天眼" — AI 思想引擎技术白皮书（现役正式版）

> **副标题**：认知防御、墓碑拦截、工业级排他事务、物理落盘与双端 Jev/Laya 智能门控淬炼的 Agent 私有记忆引擎
>
> **版本号**：`v1.5.1-baize` · 2026-09-21（现役正式版）
> **架构代号**：「天禄·天眼」（Tian Lu · 辟邪御灵，天眼辨真）
> **作者**：TIAN（大老板） & 夭夭（资深技术总监兼贴身助理）
> **审查与仲裁**：Step-5-Preview（600B MoE 深度探伤） & Claude Opus（首席架构终审把关）

---

## 摘要（Executive Summary）

白泽（Bai Ze）自 v1.5.0 迈向 **v1.5.1「天禄·天眼」**，在巩固了“认知防线 + 存储物理落盘”的基石之上，完成了从“机械正则/死板阈值”到“**双端 System One 决策模型智能门控（TypeSafe Jev + Laya 兜底）**”的质的飞跃。

本版本彻底解决了困扰自托管 AI Agent 的四大核心痛点：
1. **记忆写入端算力空转与记忆库水化**：引入 TypeSafe Jev 旁路判别门控（Fast Filter），在写入潮浪前置毫秒级拦截闲聊废话与瞬态过渡语（拦截率 > 70%），大幅削减 DeepSeek/GLM 提取算力消耗；
2. **检索召回端“死板正则”与“语义盲区”**：告别陈旧死板的关键词与问号正则嗅探，升级为 Jev 召回判别模型，精准识别隐式记忆调用意图；同时实现显式口令 0ms 白名单直通与 Laya HF Space 零鉴权弹性兜底，具备双重 Fail-open 容灾；
3. **认知洗白与借尸还魂（v1.5.0 继承）**：确立「结构不可达 > 提示词约定」铁律，建立 Origin 身份物理硬隔离与 SHA-256 墓碑拦截表（`rejected_values`），旧事实被推翻后换 ID 亦绝不可复活；
4. **SQLite WAL 锁升级与断电丢日志（v1.5.0 继承）**：`get_db(write=True)` 引入 `BEGIN IMMEDIATE` 物理消灭多线程读升写死锁，`wal.py` 注入内核 `os.fsync()` 确保硬件断电零丢失。

经 Claude Opus 首席架构师终审裁定：**“修复教科书级正确，门控 Fail-open 机制设计严密，架构选型对于单租户自托管场景处于‘恰好正确’的黄金抽象层级，免检投产。”**

---

## 一、 系统定位与架构全景

### 1.1 核心设计哲学
1. **轻量自托管铁律**：纯血 Debian 13 环境，零外部臃肿依赖（无 JVM、无分布式 etcd/MinIO/Pulsar），单进程原生 Python + SQLite WAL，常驻端口 `8767`，内存开销 < 120MB，毫秒级响应。
2. **进门过滤废话，出门智能召回**：
   - **写入门神**：TypeSafe Jev 前置拦截纯闲聊、无持久价值的过渡句，保护知识库纯度；
   - **召回门神**：Jev 智能决策用户意图，配合白名单直通，实现“该想时心领神会，不该想时绝不添乱”。
3. **Fail-open 容灾铁律**：外部门控网络抖动或超时（1.5s）时，一律自动降级放行或走正则兜底，坚决不阻塞正常会话与记忆落盘。
4. **结构不可达 > 提示词约定**：绝不依赖 LLM “请不要提取推测” 的软性约定，在输入解析层直接按角色机械盖戳，非用户亲陈事实在代码层物理剥夺进入 CoreMemory 的权限。
5. **耐久性至上（Durability First）**：应用层 WAL 必须经过 `f.flush()` 与 `os.fsync()` 穿透内核 Page Cache，落盘才算数。

### 1.2 神兽命名体系演进
| 版本 | 代号 | 核心里程碑 |
| :--- | :--- | :--- |
| v1.0 ~ v1.3 | 初啼 / 辟邪 | 吸收 aiduMEM、玄铁架构，确立 Ebbinghaus 衰减与 Cross-Encoder 重排 |
| v1.4.0 ~ v1.4.1 | 陆吾 | 架构攻坚，Voyage 双引擎上线，向量黑洞根除，点火直达 |
| v1.4.2 | 陆吾·双链 | 提取器高可用主备双链（DeepSeek/GLM/Atria/Ling）与显式失败拒写 |
| v1.5.0 | 天禄 | 四道认知防线 + 墓碑拦截 + BEGIN IMMEDIATE 排他事务 + WAL 物理落盘 |
| **v1.5.1** | **天禄·天眼（现役）** | **双端 System One 智能门控（TypeSafe Jev 主用 + Laya HF 兜底 + Fail-open 容灾）** |

---

## 二、 核心机制与技术实现（v1.5.1 关键升级）

### 2.1 双端智能门控体系（Jev Gate & Memory Gate v1.5.1）
- **写入端前置旁路门控（Ingest Fast Filter）**：
  - 模块挂载于 `modules/jev_gate.py`，在 `on_wave_flush` 与 `_store_extracted_facts` 入口处执行。
  - 调用 Jev `systemone` 判别模型，评估文本长期记忆价值（`threshold=0.25`）。判定为 `ephemeral` 纯闲聊时直接返回空，跳过后续大模型抽取与存储链，节约 70% 无效 Token。
  - **WAL 崩溃重放隔离**：`is_replay=True` 时绝对绕过 JevGate，确保历史灾备恢复数据完整无遗漏。
- **召回端智能门神与多级降级（Search Smart Gate）**：
  - **白名单直通（0ms 极速通道）**：
    - 纠正信号（`CORRECTION_PATTERNS`，如“不对/记错了”）、显式搜索口令（`EXPLICIT_SEARCH_PATTERNS` / `GATE_PASS_PHRASES`，如“搜一下/查一下/回忆一下”）直接放行，不走外部网络 API。
    - 极短文本（< 6 字符）或纯确认词（“好的/收到/ok”）直接 0ms 拦截，不翻记忆库。
  - **Jev 语义意图判定（主用）**：
    - 对自然对话评估是否需要检索私有事实/配置/偏好（`search_threshold=0.35`，超时 1.5s）。
  - **Laya 弹性兜底（一级备用）**：
    - 当 Jev 网络超时或异常时，自动回退请求 Hugging Face Laya 在线 Space 判别。
  - **正则与 Fail-open 兜底（终级护栏）**：
    - 外部 API 全部故障时，自动落入原有 `QUESTION_PATTERNS` 问句正则或放行，绝不抛 500、绝不阻塞对话。

### 2.2 四道认知防线（Cognitive Defense）
- **防线一：Origin 身份硬隔离（防 Factwashing）**
  - 解析对话输入序列，消息流只要包含用户陈述，强制标记 `origin='user'`；纯助手发言打标 `origin='agent-inferred'`；工具输出打标 `origin='tool-output'`。
  - `_sync_core_memory_from_facts` 设置物理门禁：非 `origin == 'user'` 的事实绝对禁止同步进 `user_profile`，从根源切断助手猜测洗白为永久画像的途径。
- **防线二：极性反转直接取代（破除 Jaccard 稀释）**
  - 在 `modules/evolution.py` 中，当检测到否定词极性翻转且核心主题重合词 $\ge 3$ 时，直接判定关系为 `replaces`（置信度 0.85），彻底抛弃旧版长句分母暴增导致置信度卡死的数学缺陷。
- **防线三：被否决事实墓碑机制（Tombstone / rejected_values）**
  - 新建 `rejected_values` 墓碑哈希表；当事实被标记为 `superseded` 时，文本经 NFKC 归一化与符号清洗后生成 SHA-256 铸入墓碑。
  - 提取入库时实行墓碑抗体比对，已被否决的事实即便换 ID 或微调语序也直接被拦截。
- **防线四：生肉回灌硬熔断**
  - 彻底拔除提取返回空时的生肉 Fallback 写入；单条事实超过 250 字符或包含 `*.*` 角色扮演动作描写的文本绝对拒签。

### 2.3 混合召回与保底初筛（Hybrid Recall + Recent Pool）
- **向量 + 倒排 + 图谱三路融合**：Voyage 1024 维 INT8 量化向量（权重 0.5） + SQLite FTS5 BM25（权重 0.3） + 实体知识图谱（权重 0.2）。
- **初筛过采样（Over-fetching）**：候选池由 Top-20 提升至 Top-100（`max(limit * 5, 25)`），确保近窗事实顺利穿透粗排。
- **活跃记忆时效保底池（Recent Pool）**：在初筛阶段直接兜底拉出近 48 小时内前 30 条关键事实（权重 0.4 保底），并叠加显式加性时效奖励（24h 内 `+0.25`，48h 内 `+0.15`），彻底根治“最新决策被历史老黄历词频淹没”的病灶。

### 2.4 工业级存储事务与物理持久化（P0 排雷）
- **`get_db(write: bool = False)` 上下文管理器**：
  - 针对写事务显式传入 `write=True`，执行 **`BEGIN IMMEDIATE`** 提前抢占 RESERVED 锁，彻底消灭高并发下从 SHARED 读锁升级为 EXCLUSIVE 写锁时引发的 `SQLITE_BUSY` 死锁。
  - 设置 `PRAGMA synchronous=NORMAL` 与 `PRAGMA journal_mode=WAL`，结合显式 `try...except rollback...finally close`，杜绝悬挂事务。
- **`wal.py` 物理刷盘（fsync）**：
  - 在 `append()` 与 `mark_complete()` 操作后，显式执行 `f.flush()` 与 `os.fsync(f.fileno())`，穿透系统页缓存，杜绝 OOM 强杀或断电下的日志蒸发。

---

## 三、 运行规格与基准实测

- **运行平台**：Debian 13 (Linux 6.12 amd64)，Python 3.11+
- **守护服务**：`systemd` 托管，自启自愈，常驻端口 `8767`
- **基准测试与健康指标**：
  - 服务探针：`/health` 全绿（6 模块 + 5 探针 100% 就绪）
  - 门控实测：闲聊文本 JevGate 过滤耗时 < 350ms，显式口令检索 0ms 直通
  - 检索性能：端到端复合检索延迟稳定在 **18ms ~ 45ms**，时效记忆 Top-1 命中率 100%
- **准出测试套件**：
  - 微观单元回归：`test_reform_regression.py`（5/5 PASSED，100% 通过）
  - 深度对抗套件：`comprehensive_reform_suite.py`（涵盖注入隔离、极性纠错、变体墓碑、生肉拒签、高并发防锁）

---

## 四、 结语

白泽 v1.5.1「天禄·天眼」以极致克制的工程架构，融合了自研认知防线与 System One 决策模型双端门控，再次印证了：**最顶级的系统韧性，永远来自对确定性逻辑与鲁棒容灾机制的精微打磨。**