# CLAUDE.md —— 白泽项目 · Claude 会话快速上手

> 本文件只写**本项目专属**内容，薄壳，不复述通用工作流。
> 通用机器 SOP（三节点分工 / Git / SSH / 部署 / 排查）见 `E:\AI工具\claude-run\CLAUDE.md`。
> 给非-Claude 模型/其他 agent 的通用工作指南见 `AGENTS.md`。

---

## 1. 这是什么

**白泽（Bai Ze）** — 面向 AI Agent 的私有持久化思想引擎 / 长期记忆中枢。
单进程 FastAPI + SQLite（WAL）+ 文件 WAL，**零外部依赖**（无 JVM / Milvus / Neo4j / Redis）。
v1.5.3「天禄·金汤」，生产端口 `8767`，日常 RSS ~80MB（6.6 万事实 + 3.2 万 INT8 向量）。

## 2. 怎么跑 / 怎么验（仅 NAS/Linux 侧，工位不跑）

```bash
uvicorn api_server:app --host 127.0.0.1 --port 8767   # 启动
curl http://127.0.0.1:8767/health                      # 健康（6 模块 + 5 探针）
curl -X POST http://127.0.0.1:8767/search_trace \
  -H "Content-Type: application/json" \
  -d '{"query": "测试", "user_id": "default"}'         # 追忆漏斗诊断
```
工位侧只做：`python -m py_compile`（语法检查）+ `git push`。**真实单测/build/部署一律 NAS。**

## 3. 代码布局（5 行）

- `api_server.py` — FastAPI 入口（写入/检索/WAL 重放/定时任务）
- `modules/hybrid_recall.py` — 混合检索（FTS5 0.3 + Voyage int8 向量 0.5 + 图谱 0.2）
- `modules/auto_dream.py` — 记忆蒸馏固化 + 过期降级事实巡检
- `modules/evolution.py` / `llm_extract.py` / `jev_gate.py` / `wal.py` — 演化建边 / LLM 提取 / 门控 / WAL
- `plugin/baize/` — Hermes MemoryProvider 插件

## 4. 本项目铁律（不要违反）

1. **Fail-open**：所有外部 I/O（embedding / rerank / LLM / 门控）必须 `try/except` 放行，绝不阻塞主流程。
2. **单进程 SQLite 足够**：**不要建议** Saga / Milvus / Neo4j / Redis 等分布式或中间件（Step-5 历史教训，单租户场景）。
3. **代码 + 文档同步**：改代码必须同步 `docs/CHANGELOG.md` / `docs/whitepaper.md` / `README.md`；修复标注 `// Issue #N`，新特性标注 `// vX.Y.Z`。
4. **防御性编程**：空值/None 边界先判后用（如 `row[0] if row else ""`）。
5. **线程安全**：沿用现有四把独立锁的模式，**不引入嵌套锁**（零死锁前提）。

## 5. 常用入口

- 写记忆：`POST /add` / `POST /api/ingest`（压缩桥归档）
- 检索：`POST /search` / `POST /search_trace`（漏斗诊断）
- 固化：`POST /api/auto-dream`（日增量 + 周全量，后台线程自动调度）
- 体检：`GET /health` / `GET /api/memory/health`

## 6. 想深入 → 读这些

- `AGENTS.md` — 项目通用 AI agent 工作指南（组织/机制/审核 checklist/陷阱）
- `docs/whitepaper.md` — 技术白皮书（架构、门控、防线、存储）
- `docs/CHANGELOG.md` — v1.0 → v1.5.3 演进与审计编年史
- `docs/AUDIT_*.md` — 历次架构审计报告（含"不要分布式"裁定的原始依据）

---

*项目专属，随时改。通用工作流不在本文件，去 `E:\AI工具\claude-run\CLAUDE.md` 看。*
