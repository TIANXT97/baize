# AGENTS.md —— 白泽项目 AI Agent 工作指南

> 本文件为 AI agent（Claude / GPT / 其他模型）提供项目上下文与工作规范。
> 跨会话、跨模型生效，确保代码审核与后续开发的一致性。

---

## 1. 项目定位

**白泽（Bai Ze）** 是一套专为长生命周期 AI Agent（如 Hermes Agent）设计的**全功能私有化持久思想引擎（Thought Engine）**。

**核心哲学**：记忆不是堆积，而是筛选；遗忘不是缺陷，而是智慧；思想不是存储，而是编织。

**架构铁律**：单进程 FastAPI + SQLite WAL + 文件 WAL，零外部依赖（无 JVM、无分布式 etcd/MinIO/Pulsar）。

---

## 2. 代码组织

```
baize-memory/
├── api_server.py          # FastAPI 主入口（端口 8767）
├── modules/               # 核心模块
│   ├── hybrid_recall.py   # 混合检索：FTS5 + Voyage int8 + 图谱多跳
│   ├── auto_dream.py      # 自动梦境/记忆固化（LLM + 规则引擎双通道）
│   ├── evolution.py       # 知识拓扑演化建边
│   ├── llm_extract.py     # LLM 多级降级链提取
│   ├── jev_gate.py        # Jev/Laya 双端智能门控
│   ├── wal.py             # WAL 预写日志 + os.fsync() 物理落盘
│   ├── decay.py           # 9 轨道艾宾浩斯遗忘衰减
│   ├── coalesce.py        # 批量防抖聚合 (Coalesce)
│   ├── memory_gate.py     # 召回端门控（口令/纠正信号白名单）
│   ├── core_memory.py     # 核心记忆块管理
│   ├── reranker.py        # Voyage/bge 双引擎重排
│   ├── fastpath.py        # 正则快提路径（毫秒级）
│   ├── quantize.py        # int8 量化公共函数
│   └── __init__.py        # 模块导出
├── plugin/baize/          # Hermes MemoryProvider 原生插件
├── scripts/               # 运维脚本
├── tests/                 # 综合压力测试套件（非标准 pytest）
├── docs/                  # 文档（白皮书、编年史、审计报告）
├── config.json            # 权威配置（含 DREX 支持注释）
└── requirements.txt       # Python 依赖
```

---

## 3. 核心机制（必须理解）

### 3.1 数据流

```
写入：/add → Coalesce → Jev 快筛 → FastPath/LLM 提取 → 锚词质检 → 向量双写(float+int8) → 演化建边 → WAL fsync → CoreMemory 同步
检索：/search → Jev 门神 → FTS5(0.3) + 向量(0.5) + 图谱(0.2) → 9 轨道衰减 → Ignition 直达(≥0.45 且 gap≥0.12) → Reranker → 返回
```

### 3.2 四道认知防线

1. **Origin 身份硬隔离**：非用户亲陈事实物理禁止同步进 `user_profile`
2. **极性反转取代**：否定词翻转直接判定 `replaces`（置信度 0.85）
3. **被否决事实墓碑**：废弃事实 SHA-256 铸入 `rejected_values` 表，换 ID/微调语序绝对拦截
4. **生肉回灌硬熔断**：提取返回空坚决零落盘，超长文本/角色动作描写绝对拒签

### 3.3 线程安全

四把独立锁，无嵌套，零死锁：
- `LLMExtractor._lock` → 保护 `_cache`
- `HybridRecall._embed_lock` → 保护 `_embed_cache`
- `CoalesceManager._lock` → 保护 `_buffers`
- `WALEngine._wal_lock` → 保护 WAL 文件写入

### 3.4 性能基准

- **运行体量**：66,727 条事实 + 32,885 条 1024 维 INT8 向量
- **日常 RSS**：75 MB ~ 80 MB（v1.5.2 游标流式 + SQLite 缓存硬锁）
- **检索延迟**：18ms ~ 28ms（端到端复合检索）
- **并发安全**：12 线程混合并发读写 0 死锁

---

## 4. 代码风格约定

### 4.1 注释规范

**必须包含**：
- **修复历史**:标注修复日期、设计决议记录、实测数据(如 `// 2026-09-23 v4 多方共识`)
- **版本标记**：新特性标注版本号（如 `// v1.5.3-hotfix`）
- **Issue 引用**：修复 issue 时标注 issue 号（如 `// Issue #1`）
- **业务背景**：Domain-specific 防御标注业务原因（如 `// Domain-specific 业务防御：矛盾清洗针对特定人物...`）

**示例**：
```python
# Issue #1: raw_fallback 写入时赋予 7 天生命周期，避免无限积累污染库
expires_at = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
```

### 4.2 错误处理模式

**Fail-open 铁律**：
```python
try:
    resp = urllib.request.urlopen(req, timeout=2.0)
except Exception as e:
    logger.debug("fail-open: %s", e)
    pass  # 放行，不阻塞
```

**防御性编程**：
```python
# Issue #4: 防御性编程——非 default 用户首次写入时 row 为 None，row[0] 会抛 TypeError。
lines = [ln for ln in (row[0] if row else "").split("\n") if ln.strip()]
```

### 4.3 命名约定

- **常量**：`UPPER_SNAKE_CASE`（如 `MIN_SEAT_SIMILARITY`）
- **私有方法**：`_leading_underscore`（如 `_seat_scores`）
- **公共方法**：`snake_case`（如 `run_distillation`）
- **配置键**：`snake_case`（如 `expires_at`）

---

## 5. 测试与验证

### 5.1 语法检查（工位侧）

```bash
# Python 语法检查（所有文件）
python -m py_compile api_server.py modules/*.py plugin/baize/__init__.py scripts/*.py tests/*.py

# 或逐文件检查
Get-ChildItem -Recurse -Filter *.py | ForEach-Object { python -m py_compile $_.FullName }
```

### 5.2 单元测试（NAS 侧，工位不跑）

- **测试套件**：`tests/comprehensive_stress_suite.py`（非标准 pytest）
- **验证项**：12 线程并发 0 死锁、50 轮检索洪水自动回落、5 大跨领域事实 100% 命中

### 5.3 端到端验证（NAS 侧）

```bash
# 启动服务
uvicorn api_server:app --host 127.0.0.1 --port 8767

# 健康检查
curl http://127.0.0.1:8767/health

# 追忆漏斗诊断
curl -X POST http://127.0.0.1:8767/search_trace \
  -H "Content-Type: application/json" \
  -d '{"query": "测试", "user_id": "default"}'
```

---

## 6. 工作流与部署

### 6.1 分工

- **工位**（Win11）：写代码、静态检查、`git push`
- **NAS**（fnOS）：build、单测、容器重启、db schema 迁移、端到端 curl 验证

### 6.2 部署模式

**按需模式**：推完 git 后**不用当场 build**。夭夭（NAS 那边的 agent）待命，老板随时说"发一下"，夭夭就 `git pull && docker compose build && up -d && health`。

### 6.3 Git 规范

- **协议**：`git@github.com:TIANXT97/baize.git` 原生 SSH
- **身份**：`TIANXT97 <770884786@qq.com>`
- **红线**：不贴 token 进 `git remote -v` URL、不 `--force` / `reset --hard` main、推 GitHub 永远 SSH

### 6.4 文档同步铁律

**代码改了，文档必须跟上**：
- `docs/CHANGELOG.md` — 记录每次版本变更
- `docs/whitepaper.md` — 同步核心机制说明
- `README.md` — 更新特性描述
- `config.json` — 在注释里补充说明（如 DREX 支持）

---

## 7. 已知边界与防御机制

### 7.1 Domain-specific 热补丁

**矛盾清洗硬编码**（`api_server.py:397-401`）：
- 针对特定人物（洋芋）在特定时期的性别认知漂移所设立的"领域专属事实墓碑"
- 属于极其收敛的业务防御，并非通用的 NLP 矛盾推断
- 新增矛盾对需手动扩展规则或引入通用 NLI（但 NLI 过重且易误杀，故维持现状）

### 7.2 防抖门槛

**Recent Pool 相似度下限**（`hybrid_recall.py:402-406`）：
- `MIN_SEAT_SIMILARITY = 0.15`
- 低于阈值不补入候选集，根治短 query 下席位挤掉真相关老事实的边界扰动

**Recent Pool 分层配额**（`hybrid_recall.py`，Issue #21）：
- `RECENT_POOL_IMPORTANCE_SLOTS = 20`（`importance DESC, id DESC`）+ `RECENT_POOL_LATEST_SLOTS = 10`（`id DESC`），按 id 去重
- 防止高密度写入高 importance 记忆时，低一档的新记忆被整体挤出保底池

**FTS 短语回退门槛**（`hybrid_recall.py:_fts_search`，Issue #21）：
- `FTS_PHRASE_MIN_HITS = 3`：多实体查询的短语命中数低于该值时继续走关键词 OR（OR 是短语的超集，不会丢结果）
- 改动会影响 `total_hits`，进而影响 `hit_factor` / `rank_norm`，调参前先看 FTS 分值量纲

### 7.3 降级事实生命周期

**raw_fallback 过期机制**（`api_server.py:480` + `auto_dream.py:_cleanup_expired_fallbacks`）：
- 写入时赋 `expires_at = now + 7d`
- AutoDream 周期巡检物理清退过期降级事实并注销向量

---

## 8. 审核 Checklist

其他模型/会话审核代码时，必须检查以下项：

- [ ] **Fail-open 铁律**：所有外部 I/O（embedding/rerank/LLM/search）是否有 `try/except` 包裹？
- [ ] **防御性编程**：`row[0]` 等可能为 `None` 的边界是否已处理？
- [ ] **线程安全**：新加的锁是否与现有四把锁（LLMExtractor、HybridRecall、CoalesceManager、WALEngine）嵌套？
- [ ] **性能**：新加的循环/查询是否引入 O(n²) 或 N+1 查询？
- [ ] **文档同步**：代码改动是否同步更新了 CHANGELOG/whitepaper/README/config？
- [ ] **Issue 引用**：修复代码是否标注了 issue 号？
- [ ] **版本标记**：新特性是否标注了版本号（如 `// v1.5.3-hotfix`）？

---

## 9. 常见陷阱与历史教训

### 9.1 不要建议分布式架构

**Step-5 的教训**：曾建议 Saga/Milvus/Neo4j，被裁定"大厂路径依赖式过度设计"。

**原因**：单租户自托管场景，向量规模 < 100 万条，SQLite + numpy/faiss-cpu 单文件方案完全够用。Milvus 的运维成本（etcd + MinIO + Pulsar）比整个系统还重。

### 9.2 不要破坏现有防御机制

- 不要移除 `try/except` 包裹（Fail-open 铁律）
- 不要移除 `rejected_values` 墓碑表查询（防借尸还魂）
- 不要移除 `_seat_scores` 的 `MIN_SEAT_SIMILARITY` 门槛（防抖）
- 不要移除 `_cleanup_expired_fallbacks` 周期巡检（防 raw_fallback 无限积累）

### 9.3 不要引入外部依赖

**禁止**：不建议引入 Redis、Kafka、Elasticsearch、Neo4j 等外部中间件。

**例外**：如需新依赖，必须在 issue 中明确说明"轻量自托管铁律"已考虑，且提供单文件/SQLite 方案无法解决的证据。

---

## 10. 相关文档

- 📜 [白泽 v1.6.0 架构白皮书](docs/whitepaper.md) — 核心系统架构、Jev/Laya 前置判别门控、认知安全与存储规范
- 📜 [全景演进与架构审计编年史](docs/CHANGELOG.md) — 涵盖 v1.0 至 v1.5.3 完整演进历史与历次架构审计结论
- 📜 [机器级 SOP（工位）](E:\AI工具\claude-run\CLAUDE.md) — 三节点分工、SSH/Git/部署规范（仅工位机器生效）

---

*本文档由工位 Claude（Kimi-K3）生成，供 AI agent 审核与后续开发参考。*
*最后更新：2026-10-12*
