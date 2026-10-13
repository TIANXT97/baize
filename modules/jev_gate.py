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

        # Backup Gate 支持 (例如 Drex v2.0 作为静默热备)
        backup_cfg = config.get("backup_gate") or {}
        self.backup_enabled = bool(backup_cfg.get("enabled", False))
        self.backup_api_key = backup_cfg.get("api_key", "")
        self.backup_api_url = backup_cfg.get("api_url", "")
        self.backup_model = backup_cfg.get("model", "")
        self.backup_timeout = float(backup_cfg.get("timeout_sec", 1.5))

        self._opener = None
        if self.proxy:
            proxy_handler = urllib.request.ProxyHandler({
                "http": self.proxy,
                "https": self.proxy
            })
            self._opener = urllib.request.build_opener(proxy_handler)

    def _call_systemone_api(self, api_url: str, api_key: str, model: str, timeout: float, payload_dict: dict) -> dict:
        """封装底层的 /v1/systemone HTTP 请求。"""
        payload_dict["model"] = model
        data = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            api_url,
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Baize/Gate-v2.0 (TypeSafe-Client)",
            },
            method="POST",
        )
        if self._opener:
            resp = self._opener.open(req, timeout=timeout)
        else:
            resp = urllib.request.urlopen(req, timeout=timeout)
        with resp:
            raw_bytes = resp.read(10 * 1024 * 1024)
        return json.loads(raw_bytes.decode("utf-8", "replace"))

    def should_filter(self, text: str) -> tuple:
        """判定文本是否应被过滤。

        Returns:
            (True, reason)  — 确定为废话，可过滤
            (False, reason) — 保留，应走提取链
        """
        # Qwen 3.8 Max 补丁：enabled=False 绝对短路
        if not self.enabled:
            return (False, "jev_disabled_fail_open")

        if not self.api_url or not self.api_key:
            return (False, "jev_not_configured_fail_open")

        # Qwen 3.8 Max 补丁：输入类型安全防御，防 AttributeError 击穿 Fail-open
        if text is None:
            return (False, "empty_passthrough")

        if isinstance(text, (bytes, bytearray)):
            try:
                text = text.decode("utf-8", "ignore")
            except Exception:
                return (False, "undecodable_passthrough")
        elif not isinstance(text, str):
            try:
                text = str(text)
            except Exception:
                return (False, "invalid_text_passthrough")

        try:
            stripped = text.strip()
        except Exception:
            return (False, "invalid_text_passthrough")

        # 短文本不调 API，直接保留交给 fastpath
        if len(stripped) < 10:
            return (False, "too_short_passthrough")

        # 垂直工程黑话极速放行，防止误杀
        jargon_keywords = ("白泽", "10router", "drex", "jev", "nas", "7890", "hysteria", "api_key", "ssh")
        lowered = stripped.lower()
        if any(k in lowered for k in jargon_keywords):
            return (False, "jargon_whitelist_allow")

        payload = {
            "questions": {
                "should_memorize": {
                    "type": "noul",
                    "instructions": (
                        "这段文本是否包含需要永久记住的用户个人档案、硬件配置、网络拓扑、否定修正或长期偏好？"
                        "重要事实、配置规则、否定禁令、个人背景或长期要求答 1；纯日常闲聊、吐槽发泄或一次性临时杂务答 0。"
                    ),
                },
                "category": {
                    "type": "choice",
                    "criteria": {
                        "identity": "用户画像、职业背景、生辰八字、称谓或身份事实",
                        "infra": "NAS、网络IP、服务器、端口、脚本、硬件或IT配置",
                        "preference": "用户审美、行为铁律、做事规范、黑名单或长期偏好",
                        "ephemeral": "日常口水、纯情绪吐槽、临时指令或一次性琐事",
                    },
                },
            },
            "state": text,
        }

        # 1. 尝试主门控 (OpenJev 26B)
        body = None
        source_label = self.model
        try:
            body = self._call_systemone_api(
                self.api_url, self.api_key, self.model, self.timeout_sec, payload
            )
        except Exception as e:
            log.warning(f"Primary gate ({self.model}) failed: {e}")
            # 2. 主门控失败，尝试备用门控 (Drex v2.0 热备)
            if self.backup_enabled and self.backup_api_url and self.backup_api_key:
                try:
                    log.info(f"Falling back to backup gate ({self.backup_model})...")
                    body = self._call_systemone_api(
                        self.backup_api_url, self.backup_api_key, self.backup_model, self.backup_timeout, payload
                    )
                    source_label = f"{self.backup_model}_backup"
                except Exception as be:
                    log.warning(f"Backup gate ({self.backup_model}) also failed: {be}")

        if not body:
            return (False, "gate_all_failed_fail_open")

        try:
            answers = body.get("answers", {})
            noul = float(answers.get("should_memorize", {}).get("noul", 1.0))
            category = str(answers.get("category", {}).get("choice", "unknown"))

            # 判定条件：noul < threshold 且 category == ephemeral → 拦截
            if noul < self.threshold and category == "ephemeral":
                return (True, f"ephemeral ({source_label}, noul={noul:.2f})")
            else:
                return (False, f"pass ({source_label}, cat={category}, noul={noul:.2f})")
        except Exception as parse_e:
            log.warning(f"JevGate answer parsing error: {parse_e}")
            return (False, f"parse_error_fallback: {parse_e}")

    # ===== v1.5.2 Search Gate =====

    def needs_memory_search(self, query: str) -> tuple:
        """召回端智能门控：判定用户查询是否需要翻记忆库。

        Returns:
            (True,  reason) — 需要召回记忆
            (False, reason) — 不需要召回
        双重 Fail-open: Jev/Drex 失败 → Laya 兜底 → 正则 fallback。
        """
        payload = {
            "questions": {
                "needs_memory": {
                    "type": "noul",
                    "instructions": (
                        "回答该用户查询是否需要调取用户的个人档案、过往历史、私有网络/设备/服务器配置或长期偏好？"
                        "涉及私人档案、私有设备配置或历史约束答 1；通用编程、常识问答、天气或日常闲聊答 0。"
                    ),
                },
            },
            "state": query,
        }

        body = None
        source_label = self.model
        try:
            body = self._call_systemone_api(
                self.api_url, self.api_key, self.model, self.timeout_sec, payload
            )
        except Exception as e:
            log.warning(f"Primary search gate ({self.model}) failed: {e}")
            if self.backup_enabled and self.backup_api_url and self.backup_api_key:
                try:
                    log.info(f"Falling back to backup search gate ({self.backup_model})...")
                    body = self._call_systemone_api(
                        self.backup_api_url, self.backup_api_key, self.backup_model, self.backup_timeout, payload
                    )
                    source_label = f"{self.backup_model}_backup"
                except Exception as be:
                    log.warning(f"Backup search gate ({self.backup_model}) also failed: {be}")

        if not body:
            log.warning("All primary/backup SystemOne search gates failed, trying Laya fallback")
            return self._call_laya_fallback(query)

        try:
            answers = body.get("answers", {})
            noul = float(answers.get("needs_memory", {}).get("noul", 0.0))

            if noul >= self.search_threshold:
                return (True, f"{source_label} (noul={noul:.2f})")
            else:
                return (False, f"{source_label} (noul={noul:.2f})")
        except Exception as e:
            log.warning(f"Search gate parse error: {e}, trying Laya fallback")
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
