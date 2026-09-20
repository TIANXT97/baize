# 白泽（Baize v1.4.2）架构与代码审计报告

**审计对象**：`api_server.py`、`modules/llm_extract.py`、`modules/decay.py`、`modules/wal.py`、`config.json`

**核心结论先行**：白泽 v1.4.2 在应用功能层实现了看似完整的长文本提取、多路召回与生命周期管理，但其**底层持久化语义、资源隔离与故障恢复机制存在多处致命缺陷**。这不是一套可以无人值守运行的工业级记忆底座，而是一个“功能演示 + 大量局部补丁”堆叠出的脆弱系统。以下问题中有若干属于**在生产环境必然触发的定时炸弹**，而非理论风险。

---

## 专项一：高并发与数据一致性安全（SQLite WAL 真实极限）

### P0：`get_db()` 上下文管理器缺失异常回滚与写事务隔离
**文件**：`api_server.py` → `get_db()`
```python
@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
```
**病理诊断**：
1.  `yield` 之后的 `conn.commit()` 只在调用块正常返回时执行。一旦业务代码在 `with get_db() as conn:` 块内抛出异常，**事务既不提交也不回滚**，直接被 `close()` 丢弃。SQLite 会隐式回滚未提交事务，但这意味着上层完全丧失了显式控制；更危险的是，若调用块内部已执行过部分 `UPDATE`/`INSERT` 且依赖后续逻辑补救，数据将处于不确定状态。
2.  未设置 `PRAGMA synchronous`。WAL 模式下若使用默认的 `FULL`，每次提交都会触发 WAL fsync，在高并发 `/ingest` 或梦境批量写入时，**写吞吐会被磁盘 I/O 直接打穿**，连锁引发 `database is locked`。
3.  未使用 `BEGIN IMMEDIATE`。多线程环境下，若事务先读后写，SQLite 可能会在升级锁时检测到写冲突，导致 `SQLITE_BUSY` 立即返回，30s 的 `busy_timeout` 形同虚设（因为死锁检测已触发）。

**修复代码（工业级事务边界）**：
```python
@contextmanager
def get_db(write: bool = False):
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")  # WAL 推荐配置，崩溃不丢已提交事务
    conn.row_factory = sqlite3.Row
    try:
        if write:
            conn.execute("BEGIN IMMEDIATE")  # 立即抢占写锁，避免锁升级死锁
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

---

### P0：`wal.py` 无 `fsync`，断电/SIGKILL 下应用层 WAL 丢失
**文件**：`modules/wal.py` → `append()` / `mark_complete()`
```python
with open(self.wal_path, "a", encoding="utf-8") as f:
    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
```
**病理诊断**：
`f.write()` 仅写入 Python 用户态缓冲区，`close()` 也只保证刷新到 OS Page Cache。**在断电或 `SIGKILL -9`（OOM Killer 或 systemd 强杀）时，OS 尚未刷盘的数据直接蒸发**。这导致“已 `append` 一条 pending，但实际日志文件里没有这条记录”的恐怖静默故障，恢复机制 `replay()` 无从感知该操作，数据一致性归零。

**修复代码**：
```python
def _append_line(self, line: str):
    with open(self.wal_path, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())  # 强制落盘，确保 Durability
```

---

### P0：`wal.py` 的 `cleanup()` 会抹除超期未完成的 Pending，导致恢复丢失
****问题定位**：当前 `cleanup()` 按时间戳粗暴删除所有超期 `Pending`。若索引写入尚未 ACK 就崩溃，`Pending` 又已过期，`replay()` 将缺失该事务的上下文，导致 WAL 已提交但 Milvus/Neo4j 实际未更新的“幽灵状态”。

**修复方案**：`cleanup()` 必须感知事务生命周期，仅清理已被主存储 checkpoint 的安全记录；对疑似僵尸的 ACTIVE 记录，应标记为 `DEAD_LETTER` 并告警，而非直接物理删除。

**修复代码**：
```python
def cleanup(self, checkpoint_lsn: int, timeout_sec: int = 300):
    retained, garbage = [], []
    for line in self._read_all_pending():
        rec = json.loads(line)
        if rec["state"] == "COMMITTED" and rec["lsn"] <= checkpoint_lsn:
            garbage.append(rec["lsn"])  # 可安全截断
        elif rec["state"] == "ACTIVE" and time.time() - rec["ts"] > timeout_sec:
            rec["state"] = "DEAD_LETTER"  # 保留现场，触发运维告警
            retained.append(json.dumps(rec))
        else:
            retained.append(json.dumps(rec))

    self._rewrite_pending(retained)
    if garbage:
        self._truncate_wal_segments(garbage)
```

---

### 专项二：混合检索（Hybrid Retrieval）的稀疏-稠密融合缺陷

**问题定位**：`score = 0.7*cosine + 0.3*bm25` 是典型的尺度灾难。向量相似度与 BM25 得分分布完全不具可比性，直接加权等价于让 BM25 主导长尾查询；且系统未引入召回后精排（Rerank），粗排误差被直接暴露给用户。

**深层影响**：跨模态查询（代码片段 vs 自然语言注释）时，某一通道的尺度偏移会整体劣化 Top-K 准确率；无 Rerank 则无法利用 query-document 细粒度交互，对否定词、实体属性的排序完全失准。

**重构方案**：采用 **Reciprocal Rank Fusion (RRF)** 消除分数尺度依赖，并引入 **两阶段检索**：粗排（RRF 混合）+ 精排（Cross-Encoder Rerank）。

**关键代码**：
```python
def hybrid_search(self, query: str, k: int = 10):
    # 1. 多路召回，放宽候选集
    vec_hits = self.vector_store.search(query, top_k=k * 4)
    kw_hits = self.bm25_index.search(query, top_k=k * 4)
    
    # 2. RRF 融合，免疫分数尺度
    rrf = defaultdict(float)
    for rank, doc_id in enumerate(vec_hits):
        rrf[doc_id] += 1.0 / (rank + 60)
    for rank, doc_id in enumerate(kw_hits):
        rrf[doc_id] += 1.0 / (rank + 60)
    
    fused = sorted(rrf.items(), key=lambda x: -x[1])
    candidate_ids = [doc_id for doc_id, _ in fused[:k * 2]]
    
    # 3. Cross-Encoder 精排
    scored = self.reranker.predict(query, candidate_ids)
    return sorted(scored, key=lambda x: -x["score"])[:k]
```

---

### 专项三：提取管线（Extraction Pipeline）的实体对齐与幻觉过滤缺失

**问题定位**：LLM 抽取的三元组直接写入图谱，未经过实体链接（Entity Linking）与原文支撑校验（Grounding）。“AI” 与 “Artificial Intelligence” 被拆为孤立节点；无原文 span 映射的三元组则纯属幻觉。

**深层影响**：图谱迅速膨胀为不可查询的噪声网络；系统可解释性归零——一旦用户质疑答案来源，无法回溯到具体 chunk。

**重构方案**：构建提取“三阶闸门”：
1. **Canonicalization**：向量近邻 + 字符串相似度将实体映射到标准 Concept ID；
2. **Grounding**：每条边必须绑定回 chunk 的原文证据，由 NLI 或 LLM 二次判定；
3. **Provenance**：将 `chunk_id`, `offset`, `confidence` 写入边元数据。

**关键代码**：
```python
class ExtractionPipeline:
    def process(self, text: str, doc_id: str, chunk_id: str):
        raw_triplets = self.llm_extract(text)
        validated = []
        for subj, rel, obj in raw_triplets:
            # 1. 实体归一化
            subj_id = self.entity_linker.canonicalize(subj, doc_id)
            obj_id = self.entity_linker.canonicalize(obj, doc_id)
            if not subj_id or not obj_id:
                continue
            
            # 2. 幻觉过滤：必须原文可证
            evidence = self.ground_triplet(subj, rel, obj, text)
            if not evidence:
                continue
            
            # 3. 溯源入库
            validated.append({
                "subject": subj_id,
                "predicate": rel,
                "object": obj_id,
                "provenance": {"chunk_id": chunk_id, "evidence": evidence},
                "confidence": self.llm_extractor.last_confidence
            })
        return validated

    def ground_triplet(self, s, r, o, text):
        prompt = (
            f"Does the following text strictly support the fact '{s} {r} {o}'?\n"
            f"Text: {text}\nAnswer YES or NO."
        )
        return text if self.nli_verifier.verify(prompt) == "YES" else None
```

---

### 专项四：演化遗忘（Evolutionary Forgetting）的时序权重衰减缺失

**问题定位**：图谱与向量库中的“事实”只增不删，没有 `valid_from` / `valid_to` 时间维度；检索时旧知识与新知识同权竞争，导致过时信息（旧版本 API、已离职关系）胜出。

**深层影响**：知识图谱沦为“数字臃肿”；版本冲突时系统无仲裁机制，用户拿到的是历史真相而非当前状态，RAG 的时间有效性丧失。

**重构方案**：引入 **Time-Decay 检索** 与 **多版本事实存储**：
1. 每条事实/边附带 `last_verified` 与 `valid_range`；
2. 检索得分乘时间衰减因子，确保新鲜事实优先；
3. 冲突事实不物理删除，而是标记 `superseded_by`，旧记录进入冷存储。

**关键代码**：
```python
class TemporalGraph:
    HALF_LIFE_DAYS = 180

    def temporal_boost(self, base_score: float, last_verified: datetime):
        delta = (datetime.utcnow() - last_verified).days
        decay = math.exp(-math.log(2) * delta / self.HALF_LIFE_DAYS)
        # 保留 30% 保底权重，避免历史永久归零
        return base_score * (0.3 + 0.7 * decay)

    def resolve_fact_conflict(self, candidates: List[Fact]) -> Fact:
        # 按生效时间取最新，旧版本标记 superseded
        latest = max(candidates, key=lambda f: f["valid_from"])
        for stale in candidates:
            if stale.id != latest.id:
                stale.status = "superseded"
                stale.superseded_by = latest.id
                self.move_to_coldstore(stale)
        return latest
```

---

### 专项五：代码重构与三大建议

#### 1. 架构层：引入 Saga 事务管理器替代裸 WAL 重放
跨异构存储（WAL + Milvus + Neo4j + ES）的写入应抽象为可补偿的 Command 链。WAL 仅作为本地日志，真正的分布式一致性由 Saga 的正向操作 + 逆向补偿保证，避免主存储间各写各的导致半成品状态。

```python
class SagaCoordinator:
    def execute(self, steps: List[SagaStep]):
        executed = []
        try:
            for step in steps:
                step.forward()
                executed.append(step)
        except Exception as e:
            for step in reversed(executed):
                step.compensate()  # 逆操作回滚
            raise SagaRollbackError(f"Rolled back {len(executed)} steps") from e
```

#### 2. 数据层：写缓冲池 + Group Commit
对 fsync 过高导致的吞吐瓶颈，采用 **Write-Behind Buffer**：小请求先入内存队列，后台批量合并写 WAL；对 WAL 使用 **Group Commit**，多事务共享一次 `fsync`，在 Durability 与 QPS 间取得平衡。

```python
class WriteBehindWAL:
    def __init__(self):
        self.buffer = []
        self.cv = Condition()
        self._start_background_committer()

    def append(self, line: str):
        with self.cv:
            self.buffer.append(line)
            self.cv.notify()

    def _background_flush(self):
        while True:
            with self.cv:
                while not self.buffer:
                    self.cv.wait()
                batch, self.buffer = self.buffer, []
            with open(self.wal_path, "a") as f:
                f.write("\n".join(batch) + "\n")
                f.flush()
                os.fsync(f.fileno())  # 一批一次 fsync
```

#### 3. 算法层：建立“检索-提取-验证”三层反馈闭环
- **粗排**：混合检索 + RRF 快速召回；
- **精排**：Cross-Encoder Rerank 提升 Top-K 精度；
- **校验**：Answer Grounding——生成时必须强制引用 Top-K 证据 span，未命中则触发查询改写或递归检索。

此闭环从架构上根除了 P0 数据丢失、专项二的融合偏差、专项三的幻觉注入与专项四的时效性缺失，使系统具备 **可恢复、可解释、可演进** 三大核心能力。