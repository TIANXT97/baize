"""JevGate — TypeSafe Jev 旁路记忆门控模块（Fast Gate / Fast Filter）。

毫秒级判别对话文本是否具备长期记忆价值。
若判定为闲聊废话（noul < threshold 且 category == ephemeral），拦截跳过昂贵 LLM 提取。
铁律：任何异常/超时/网络错误一律 Fail-open（放行），零丢记忆风险。
"""

import json
import logging
import urllib.request
import urllib.error

log = logging.getLogger("baize")


class JevGate:
    """轻量级前置判别器：调用 TypeSafe System One API 判定文本是否为废话。

    v1.5.2: 新增 needs_memory_search() — 召回端智能门控（Jev 主用 + Laya HF 兜底）。
    """

    def __init__(self, config: dict):
        self.enabled = bool(config.get("enabled", False))
        self.api_key = config.get("api_key", "")
        self.api_url = config.get("api_url", "https://api.typesafe.ai/v1/systemone")
        self.model = config.get("model", "jev-latest")
        self.threshold = float(config.get("threshold", 0.25))
        self.search_threshold = float(config.get("search_threshold", 0.35))
        self.timeout_sec = float(config.get("timeout_sec", 1.5))
        self.proxy = config.get("proxy", "").strip()
        self.fallback_laya_url = config.get("fallback_laya_url", "").strip()
        self._opener = None
        if self.proxy:
            proxy_handler = urllib.request.ProxyHandler({
                "http": self.proxy,
                "https": self.proxy
            })
            self._opener = urllib.request.build_opener(proxy_handler)

    def should_filter(self, text: str) -> tuple:
        """判定文本是否应被过滤。

        Returns:
            (True, reason)  — 确定为废话，可过滤
            (False, reason) — 保留，应走提取链
        """
        # 短文本不调 API，直接保留交给 fastpath
        if len(text.strip()) < 10:
            return (False, "too_short_passthrough")

        try:
            payload = {
                "model": self.model,
                "questions": {
                    "should_memorize": {
                        "type": "noul",
                        "instructions": (
                            "Does this text contain permanent user facts, personal profile details, "
                            "hardware/network architecture rules, or long-term preferences that should "
                            "be permanently recorded into long-term memory? Reply 1 for permanent "
                            "facts/configs, 0 for casual chat, greetings, temporary tasks or fleeting chatter."
                        ),
                    },
                    "category": {
                        "type": "choice",
                        "criteria": {
                            "identity": "User profile, physiological traits, career, exam, or identity facts",
                            "infra": "NAS, networking, servers, scripts, deployment or IT config",
                            "ephemeral": "Casual chat, temporary instructions, disposable chatter",
                        },
                    },
                },
                "state": text,
            }

            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                self.api_url,
                data=data,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            if self._opener:
                resp = self._opener.open(req, timeout=self.timeout_sec)
            else:
                resp = urllib.request.urlopen(req, timeout=self.timeout_sec)
            body = json.loads(resp.read().decode("utf-8"))
            answers = body.get("answers", {})

            noul = float(answers.get("should_memorize", {}).get("noul", 1.0))
            category = str(answers.get("category", {}).get("choice", "unknown"))

            # 判定条件：noul < threshold 且 category == ephemeral → 拦截
            if noul < self.threshold and category == "ephemeral":
                return (True, f"ephemeral (noul={noul:.2f})")
            else:
                return (False, f"pass (cat={category}, noul={noul:.2f})")

        except Exception as e:
            # 铁律：Fail-open，任何异常一律放行
            log.warning(f"JevGate error (fail-open, passing through): {e}")
            return (False, f"error_fallback: {e}")

    # ===== v1.5.2 Search Gate =====

    def needs_memory_search(self, query: str) -> tuple:
        """召回端智能门控：判定用户查询是否需要翻记忆库。

        Returns:
            (True,  reason) — 需要召回记忆
            (False, reason) — 不需要召回
        双重 Fail-open: Jev 失败 → Laya 兜底 → 正则 fallback。
        """
        try:
            payload = {
                "model": self.model,
                "questions": {
                    "needs_memory": {
                        "type": "noul",
                        "instructions": (
                            "Does answering this user query require recalling user's personal "
                            "profile, past history, private network/device/server configurations, "
                            "or long-term preferences? Reply 1 for private/personal queries, "
                            "0 for generic programming questions, general knowledge, weather, "
                            "or casual chat."
                        ),
                    },
                },
                "state": query,
            }

            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                self.api_url,
                data=data,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            if self._opener:
                resp = self._opener.open(req, timeout=self.timeout_sec)
            else:
                resp = urllib.request.urlopen(req, timeout=self.timeout_sec)
            body = json.loads(resp.read().decode("utf-8"))
            answers = body.get("answers", {})
            noul = float(answers.get("needs_memory", {}).get("noul", 0.0))

            if noul >= self.search_threshold:
                return (True, f"jev (noul={noul:.2f})")
            else:
                return (False, f"jev (noul={noul:.2f})")

        except Exception as e:
            log.warning(f"JevGate.needs_memory_search failed: {e}, trying Laya fallback")
            return self._call_laya_fallback(query)

    def _call_laya_fallback(self, query: str) -> tuple:
        """HF Laya 兜底：Jev 不可用时走 Gradio Space SSE 接口。

        失败则回退到 regex fallback 标记，由 MemoryGate 用原有正则兜底。
        """
        if not self.fallback_laya_url:
            log.warning("Laya fallback URL not configured, returning regex_fallback")
            return (False, "regex_fallback")

        try:
            # Step 1: POST 获取 event_id
            payload = json.dumps({"data": [query]}).encode("utf-8")
            req = urllib.request.Request(
                self.fallback_laya_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=self.timeout_sec)
            event_body = json.loads(resp.read().decode("utf-8"))
            event_id = event_body.get("event_id", "")
            if not event_id:
                log.warning("Laya fallback: no event_id returned")
                return (False, "regex_fallback")

            # Step 2: GET SSE 轮询结果
            sse_url = f"{self.fallback_laya_url}/{event_id}"
            sse_req = urllib.request.Request(sse_url, method="GET")
            sse_resp = urllib.request.urlopen(sse_req, timeout=self.timeout_sec + 1)
            sse_text = sse_resp.read().decode("utf-8")

            # 解析 SSE data 行
            noul = 0.0
            for line in sse_text.split("\n"):
                line = line.strip()
                if line.startswith("data:"):
                    try:
                        d = json.loads(line[5:].strip())
                        if isinstance(d, list) and d:
                            # Gradio 返回 [result_text] 或 [{...}]
                            item = d[0]
                            if isinstance(item, (int, float)):
                                noul = float(item)
                            elif isinstance(item, dict):
                                noul = float(item.get("noul", 0.0))
                            elif isinstance(item, str):
                                # 尝试解析文本中的数值
                                try:
                                    noul = float(item)
                                except ValueError:
                                    noul = 0.5 if any(kw in item.lower() for kw in ["yes", "true", "1"]) else 0.0
                    except (json.JSONDecodeError, ValueError, IndexError):
                        continue

            if noul >= self.search_threshold:
                return (True, f"laya_fallback (noul={noul:.2f})")
            else:
                return (False, f"laya_fallback (noul={noul:.2f})")

        except Exception as e:
            log.warning(f"Laya fallback also failed: {e}, returning regex_fallback")
            return (False, "regex_fallback")
