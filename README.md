<div align="center">

# 🏛️ 白泽 (Bai Ze)

### 面向 AI Agent 的私有持久化思想引擎 · 生产就绪级长期记忆中枢
**Full-Stack Free, Self-Evolving, High-Reliability Private Thought Engine for AI Agents**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11%2B-brightgreen.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/Framework-FastAPI-teal.svg)](https://fastapi.tiangolo.com)
[![Release: v1.4.1](https://img.shields.io/badge/Release-v1.4.1--baize-orange.svg)](https://github.com/TIANXT97/baize)
[![Platform: Linux/Debian](https://img.shields.io/badge/Platform-Debian%2013%20Native-blue.svg)](#)

</div>

---

## 📖 项目简介 (Overview)

**白泽（Bai Ze）** 是一套专为长生命周期 AI Agent（如 Hermes Agent 等）设计的**全功能私有化持久思想引擎（Thought Engine）**。

它坚决拒绝传统记忆方案中“无脑向量堆积、断电即丢、检索无序、长上下文费用失控”的痼疾，深度融合了**艾宾浩斯分轨遗忘衰减、知识拓扑演化建边、意图门控、潮浪波次防抖聚合、双模型混合检索（FTS5 + Voyage int8 向量 + 图谱多跳）、WAL 预写日志死信熔断与两段式灾备**。

> **核心哲学**：  
> *“记忆不是堆积，而是筛选；遗忘不是缺陷，而是智慧；思想不是存储，而是编织。”*

---

## ✨ 核心特性 (Key Features)

- ⚡ **点火直达机制 (Ignition Bypass)**：针对混合检索量纲深度校准，当 Top-1 记忆处于绝对高置信度区间时直接秒回保送，跳过外部 Rerank 网络延迟，响应时延从 350ms 骤降至 **15~40ms**。
- 🌊 **潮浪缓冲聚合 (Coalesce WaveBuffer)**：对话流采用时间窗口 + 动作触发波次防抖聚合，批量提取事实，**节省 80%+ 的 LLM 抽取 Token**。
- ⏳ **9 轨道艾宾浩斯遗忘衰减 (9-Lane Ebbinghaus Decay)**：
  - `identity`（身份）、`preference`（偏好）：**永久零衰减**；
  - `rule`（铁律）、`procedural`（经验）、`knowledge`（知识）：缓慢衰减；
  - `emotion`（情绪）、`general`（过渡闲聊）：平滑快速淡出。
- 🛡️ **工业级持久性与 WAL 死信熔断 (WAL & Dead-Letter Failsafe)**：
  - 严格践行“先记账、再干活、干完销账”的两阶段事务；
  - 崩溃自愈重放，具备 `dead_letter` 毒数据熔断机制（失败 >3 次自动隔离），**服务绝不卡死**。
- 🔍 **追忆漏斗全链路透视 (Recall Funnel · search_trace)**：开放 `POST /search_trace` 端点，FTS、向量、图谱、衰减与重排五阶段耗时与候选淘汰明明白白，彻底告别“搜不到”的黑盒。
- 🌉 **上下文压缩桥接 (Compaction Bridge)**：Hermes Agent 压缩丢弃长历史前，规则式提取工具输出与关键事实通过 `/api/ingest` 归档并**全量补齐 1024 维 Voyage 语义向量**，根除向量黑洞。
- 🔒 **全链路并发零死锁**：四大独立互斥锁物理隔离，写事务与网络 I/O 彻底解耦，统一配置 30 秒 `busy_timeout` 防爆排队。

---

## 🏗️ 架构拓扑 (Architecture)

```
        ┌────────────────────────────────────────────────────────┐
        │                 AI Agent 认知交互层                     │
        └───────────────────────────┬────────────────────────────┘
                                    │
                         REST API / Plugin 钩子
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        白泽 v1.4.1 内核架构                            │
│                                                                        │
│  ┌──────────────────────┐              ┌────────────────────────────┐  │
│  │     写入与演化链路   │              │        追忆与检索链路      │  │
│  │                      │              │                            │  │
│  │  Coalesce 潮浪缓冲   │              │  MemoryGate 意图门控       │  │
│  │         │            │              │             │              │  │
│  │  FastPath 规则提取   │              │  FTS5 词项召回 (BM25)      │  │
│  │         │            │              │  (提前过滤 superseded)      │  │
│  │  LLM 语义提取 (9轨)  │              │             │              │  │
│  │         │            │              │  Voyage 向量余弦 (int8)    │  │
│  │  WAL 预写全局锁记账  │              │             │              │  │
│  │         │            │              │  三来源打分量纲归一融合    │  │
│  │  SQLite 纯本地写事务 │              │             │              │  │
│  │         │            │              │  Knowledge 图谱多跳扩展    │  │
│  │  Voyage 向量化 (1024)│              │             │              │  │
│  │         │            │              │  Ebbinghaus 遗忘分轨衰减   │  │
│  │  Evolution 演化建边  │              │             │              │  │
│  │         │            │              │  Ignition 点火高置信直达   │  │
│  │  WAL 销账闭环完成    │              │             │              │  │
│  │                      │              │  Cross-Encoder 潮汐重排    │  │
│  └──────────────────────┘              └────────────────────────────┘  │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                         数据与持久化底座                         │  │
│  │   facts.db (SQLite-vec)  ·  wal.jsonl (死信熔断)  ·  Debian 13   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 快速启动 (Quick Start)

### 1. 环境准备与安装
```bash
git clone https://github.com/TIANXT97/baize.git
cd baize

# 推荐 Python 3.11+ 虚拟环境
python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

### 2. 配置环境变量
```bash
cp .env.example .env
# 编辑填入你的 API Key (提取器支持主/备双链自动降级，任意 OpenAI 兼容端点均可；
# 例：主用免费羊毛模型 + 备用 Ling-3.0-flash(百灵) / Voyage AI 200M 免费额度做向量)
```

### 3. 启动服务
```bash
uvicorn api_server:app --host 127.0.0.1 --port 8767
```

### 4. 验证服务状态
```bash
curl http://127.0.0.1:8767/health
```
返回 `status: ok` 且 6 大模块、5 大探针全绿即代表就绪！

---

## 🔌 接入 Hermes Agent

白泽提供了原生 Hermes MemoryProvider 插件。只需将 `plugin/baize` 拷贝至 Hermes 插件目录：
```bash
cp -r plugin/baize ~/.hermes/plugins/
```
在 Hermes 配置文件 `config.yaml` 中启用：
```yaml
memory:
  provider: baize
```

---

## 📚 详细技术文档 (Documentation)

- 📜 [白泽 v1.5.0 完整技术白皮书（天禄现役版）](docs/whitepaper.md) — 核心系统架构、认知防线与存储规范
- 📜 [全景演进与架构审计编年史](docs/CHANGELOG.md) — 涵盖 v1.0 至 v1.5.0 完整演进历史与历次架构审计结论

---

## 📄 开源许可证 (License)

本项目基于 [MIT License](LICENSE) 协议开源。
