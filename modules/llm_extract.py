"""LLM Extract - extract facts from conversation using LLM."""
import json
import urllib.request
import re
import hashlib
import time
import logging
import threading
from collections import OrderedDict
from typing import List, Dict, Optional, Tuple

log = logging.getLogger("baize")

EXTRACT_PROMPT = """从以下文本中提取所有事实性信息。每条信息都值得记住。

你必须输出JSON数组，每个元素包含fact、category、importance三个字段：
[{"fact": "完整描述句", "category": "分类", "importance": 0.5}]

分类规则（category 必须是以下 9 类之一，不确定时用 general）：
- identity：姓名、住址、职业、生日、身份信息（例：用户叫TIAN）
- preference：喜好、偏好、习惯（例：用户喜欢咖啡）
- emotion：情绪感受（例：用户最近工作压力很大）
- lesson：踩坑、报错、教训、经验（例：非 root 跑 systemctl --user 报 Failed to connect to bus）
- rule：必须、禁止、规则、底线（例：用户要求服务必须开机自启）
- procedural：步骤、配置、操作、流程、方法（例：baize 服务由 systemd 用户服务托管，崩溃 5 秒自动重启）
- evidence：发现、测试、验证、确认的事实（例：用户确认 baize 服务重启后 5 秒自动恢复）
- knowledge：技术知识、API、版本、路径、地址、端口（例：SQLite WAL 模式写入性能更好）
- general：客户、项目、工作内容、关系、经历等其他事实（例：用户的客户包括欧莱雅）

fact必须是完整中文描述句。例如：
- 输入"我的客户包括欧莱雅" → {"fact": "用户的客户包括欧莱雅", "category": "general", "importance": 0.5}
- 输入"我叫TIAN" → {"fact": "用户叫TIAN", "category": "identity", "importance": 0.8}
- 输入"我喜欢咖啡" → {"fact": "用户喜欢咖啡", "category": "preference", "importance": 0.6}
- 输入"踩过坑：非 root 跑 systemctl --user 报 Failed to connect to bus" → {"fact": "非 root 跑 systemctl --user 会报 Failed to connect to bus", "category": "lesson", "importance": 0.6}
- 输入"baize 服务由 systemd 用户服务托管，崩溃 5 秒自动重启" → {"fact": "baize 服务由 systemd 用户服务托管，崩溃 5 秒自动重启", "category": "procedural", "importance": 0.6}

**实体完整性铁律**：提取事实时必须显式补齐主语、宿主与操作主体环境（例如：禁止只说“裁定保留两个模型”或“修改了配置”，必须补齐为“在 10router 中裁定保留两个模型”、“在 NAS 宿主上修改了配置”；禁止出现脱离上下文的无主断句）。

重要：只要是事实性信息就提取，不要跳过任何内容。如果没有事实，返回[]。

文本：
"""

# E1: 与 decay.LANE_CONFIG 对齐的 9 类分类体系（修复前仅 4 类，lesson/rule/
# procedural/knowledge 等 lane 永远提不出来）
VALID_CATEGORIES = (
    "identity", "preference", "emotion", "lesson", "rule",
    "procedural", "evidence", "knowledge", "general",
)


class LLMExtractor:
    """Extract facts from text using LLM with LRU cache support."""

    def __init__(self, api_url: str, api_key: str, model: str = "Ling-3.0-flash",
                 cache_ttl_sec: int = 3600, cache_max: int = 256,
                 timeout_sec: int = 30, max_tokens: int = 2048,
                 fallbacks: Optional[List[Dict]] = None):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.cache_ttl_sec = cache_ttl_sec
        self.cache_max = cache_max
        # 2026-09-15：超时 15s→30s（可配），避免偶发慢响应被误判为不可用
        self.timeout_sec = timeout_sec
        self.max_tokens = max_tokens
        # 调用链：主端点 + 备用端点，逐级降级。元素 {api_url, api_key, model}
        self.chain: List[Dict] = [
            {"api_url": self.api_url, "api_key": api_key, "model": model}
        ]
        for fb in (fallbacks or []):
            if fb.get("api_url") and fb.get("api_key") and fb.get("model"):
                self.chain.append({
                    "api_url": str(fb["api_url"]).rstrip("/"),
                    "api_key": fb["api_key"],
                    "model": fb["model"],
                })
        # LRU cache: {text_hash: (expire_at, result)}
        self._cache: OrderedDict[str, Tuple[float, List[Dict]]] = OrderedDict()
        self._lock = threading.Lock()

    def _cache_key(self, text: str) -> str:
        """Generate stable cache key from text."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> Optional[List[Dict]]:
        """Return cached result if valid, else None."""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            expire_at, result = entry
            if time.time() >= expire_at:
                del self._cache[key]
                return None
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            return result

    def _cache_put(self, key: str, result: List[Dict]):
        """Insert result into cache, evicting least recently used if full."""
        with self._lock:
            now = time.time()
            expire_at = now + self.cache_ttl_sec
            self._cache[key] = (expire_at, result)
            self._cache.move_to_end(key)
            # Evict oldest entries beyond max size
            while len(self._cache) > self.cache_max:
                self._cache.popitem(last=False)

    def _call_endpoint(self, endpoint: Dict, prompt: str) -> Tuple[Optional[str], str]:
        """打单个端点，最多重试 1 次。返回 (content, fail_reason)。

        content 为 None 表示该端点彻底不可用（超时/网络/HTTP/响应体异常）。
        """
        last_err = ""
        for attempt in range(2):
            try:
                payload = {
                    "model": endpoint["model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": self.max_tokens,
                    "temperature": 0.1,
                }
                # 针对 deepseek 等推理模型，在记忆事实提取岗位显式关闭推理思考，提速且防止吞爆预算
                if "deepseek" in endpoint["model"].lower():
                    payload["reasoning_effort"] = "none"

                data = json.dumps(payload).encode()
                req = urllib.request.Request(
                    f"{endpoint['api_url']}/chat/completions",
                    data=data,
                    headers={
                        "Authorization": f"Bearer {endpoint['api_key']}",
                        "Content-Type": "application/json",
                    },
                )
                resp = urllib.request.urlopen(req, timeout=self.timeout_sec)
                result = json.loads(resp.read())
                content = result["choices"][0]["message"]["content"]
                if content is None:
                    last_err = "empty content field"
                    continue
                return content, ""
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                log.warning(
                    f"LLM extraction failed on {endpoint['model']} "
                    f"(attempt {attempt + 1}/2, timeout={self.timeout_sec}s): {e}"
                )
                if attempt == 0:
                    log.info("Retrying LLM extraction...")
        return None, last_err

    def _call_llm(self, prompt: str) -> Tuple[Optional[str], str, str]:
        """按调用链逐级降级打端点。

        返回 (content, used_model, fail_reason)：
        - content 非 None：某个端点给出了可读响应（used_model = 该模型名）
        - content 为 None：整条链全部失败（fail_reason 保留最后一次错误，供告警）
        """
        reasons = []
        for endpoint in self.chain:
            content, err = self._call_endpoint(endpoint, prompt)
            if content is not None:
                if endpoint is not self.chain[0]:
                    log.warning(
                        f"LLM extraction degraded to fallback endpoint "
                        f"'{endpoint['model']}'"
                    )
                return content, endpoint["model"], ""
            reasons.append(f"{endpoint['model']}: {err}")
        return None, "", " | ".join(reasons)

    def extract(self, text: str, source: str = "hermes") -> List[Dict]:
        """Extract facts from text, with LRU cache."""
        if not text.strip() or len(text.strip()) < 5:
            return []

        # Check cache first
        cache_key = self._cache_key(text)
        cached = self._cache_get(cache_key)
        if cached is not None:
            log.info(f"LLM extract cache HIT (key={cache_key[:12]}...), "
                     f"returning {len(cached)} facts")
            # Update source on cached results (source is per-call context)
            for f in cached:
                f["source"] = source
            return cached

        prompt = EXTRACT_PROMPT + text
        content, used_model, fail_reason = self._call_llm(prompt)
        if content is None:
            # 整条链全部失败：不返回 []（那会被上层当成"无事实"而静默降级），
            # 而是抛异常让调用方明确感知——只有"模型确实答了但没事实"才写空。
            log.error(f"LLM extraction chain exhausted: {fail_reason}")
            raise RuntimeError(f"LLM extraction unavailable: {fail_reason}")

        log.info(f"LLM raw response [{used_model}]: {content[:200]}")
        facts = self._parse_facts(content)
        for f in facts:
            f["source"] = source
        log.info(f"LLM extracted {len(facts)} facts (model={used_model})")

        # Store in cache (deep copy to avoid mutation side-effects)
        import copy
        self._cache_put(cache_key, copy.deepcopy(facts))
        return facts

    def _parse_facts(self, content: str) -> List[Dict]:
        """Parse fact JSON from LLM response."""
        content = content.strip()

        # Remove markdown code blocks
        content = re.sub(r"```json\s*", "", content)
        content = re.sub(r"```\s*", "", content)

        # Try to find JSON array
        start = content.find("[")
        end = content.rfind("]")
        if start >= 0 and end > start:
            try:
                facts = json.loads(content[start:end + 1])
                if isinstance(facts, list):
                    valid = []
                    for f in facts:
                        if not isinstance(f, dict):
                            continue
                        # Handle wrong format (key-value instead of fact)
                        if "fact" not in f and len(f) >= 1:
                            pairs = list(f.items())
                            if len(pairs) == 1:
                                k, v = pairs[0]
                                f = {"fact": f"用户的{k}是{v}", "category": "general", "importance": 0.5}
                            else:
                                continue
                        elif "fact" not in f:
                            continue
                        f.setdefault("category", "general")
                        f.setdefault("importance", 0.5)
                        f.setdefault("lane", f["category"])
                        # Normalize category
                        if f["category"] not in VALID_CATEGORIES:
                            f["category"] = "general"
                            f["lane"] = "general"
                        # Clamp importance to 0-1
                        f["importance"] = max(0.0, min(1.0, float(f["importance"])))
                        if len(str(f["fact"])) >= 3:
                            valid.append(f)
                    return valid
            except json.JSONDecodeError:
                pass

        # Fallback: try individual JSON objects
        objects = re.findall(r"\{[^{}]+\}", content)
        if objects:
            valid = []
            for obj_str in objects:
                try:
                    obj = json.loads(obj_str)
                    if "fact" in obj and len(str(obj["fact"])) >= 3:
                        obj.setdefault("category", "general")
                        obj.setdefault("importance", 0.5)
                        obj.setdefault("lane", obj["category"])
                        valid.append(obj)
                except json.JSONDecodeError:
                    continue
            if valid:
                return valid

        return []
