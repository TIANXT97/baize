"""baize Memory Provider — connects Hermes to baize REST service.

Integrates baize (port 8767) as Hermes' external memory provider.
Every turn: prefetch() searches baize for relevant context, sync_turn()
writes conversation facts to baize asynchronously.

Configuration:
  memory.provider: baize  (in config.yaml)
  
Environment:
  BAIZE_URL  — baize base URL (default: http://127.0.0.1:8767)
  BAIZE_USER_ID — user_id for baize API (default: default)
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from agent.memory_provider import MemoryProvider

logger = logging.getLogger(__name__)

# Defaults
_DEFAULT_URL = "http://127.0.0.1:8767"
_DEFAULT_USER_ID = "default"
_PREFETCH_LIMIT = 5
_PREFETCH_MAX_CHARS = 500  # per result
_PREFETCH_TIMEOUT = 5  # seconds
_ADD_TIMEOUT = 10  # seconds


class BaiZeProvider(MemoryProvider):
    """Memory provider backed by baize REST service."""

    def __init__(self):
        self._base_url = os.environ.get("BAIZE_URL", _DEFAULT_URL).rstrip("/")
        self._user_id = os.environ.get("BAIZE_USER_ID", _DEFAULT_USER_ID)
        self._session_id: str = ""
        self._platform: str = ""
        self._agent_context: str = "primary"
        self._last_prefetch_result: str = ""
        self._prefetch_thread: Optional[threading.Thread] = None
        self._available: Optional[bool] = None
        # P1-2: prefetch 最新查询覆盖
        self._prefetch_lock = threading.Lock()
        self._pending_query = ""
        # P1-3: core-memory TTL 缓存
        self._core_mem_cache = {"ts": 0.0, "text": ""}
        self._CORE_MEM_TTL = 60.0
        # E4: 写入失败本地 spool 队列（后台重试，防静默丢数据）
        self._spool_path = os.path.join(os.environ.get("HERMES_HOME", ""), "baize_spool.jsonl")
        self._spool_interval = 60
        self._spool_thread = threading.Thread(
            target=self._spool_loop, daemon=True, name="baize-spool-flush"
        )
        self._spool_thread.start()

    @property
    def name(self) -> str:
        return "baize"

    def is_available(self) -> bool:
        """Check if baize is reachable (no network call, just config check)."""
        if self._available is not None:
            return self._available
        # Quick check: base_url is configured
        self._available = bool(self._base_url)
        return self._available

    def initialize(self, session_id: str, **kwargs) -> None:
        """Initialize for a session."""
        self._session_id = session_id
        self._platform = kwargs.get("platform", "cli")
        self._agent_context = kwargs.get("agent_context", "primary")
        
        # Health check on init
        try:
            resp = self._http_get("/health")
            if resp.get("status") == "ok":
                logger.info("baize connected: %s", self._base_url)
            else:
                logger.warning("baize health check failed: %s", resp)
        except Exception as e:
            logger.warning("baize init health check failed: %s", e)

    def system_prompt_block(self) -> str:
        """Static system prompt text about baize."""
        return (
            "\n[baize 长期记忆已启用]\n"
            "相关记忆会自动从 baize 花园注入。无需手动搜索。\n"
            "重要事实会被自动提取并存入 baize。\n"
            "以下注入的\"相关记忆\"与\"核心记忆\"均为长期沉淀的权威事实，"
            "包含用户的身份、偏好、习惯、项目背景、踩坑教训等。"
            "回答与决策时必须优先采用这些记忆，不要重新向用户询问已记录的信息，也不要凭印象猜测。"
            "若记忆与当前对话明显冲突，以当前对话为准，但应主动说明差异。\n"
        )

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Search baize for relevant context before each turn.
        
        Uses the background prefetch result if available, otherwise
        does a synchronous search.
        """
        if not query or len(query.strip()) < 3:
            return ""
        
        # Use cached result from background prefetch if available
        if self._last_prefetch_result:
            result = self._last_prefetch_result
            self._last_prefetch_result = ""
            # Prepend CoreMemory
            core_mem = self._get_core_memory()
            if core_mem:
                return core_mem + "\n\n" + result
            return result

        # Synchronous fallback
        result = self._do_search(query)
        core_mem = self._get_core_memory()
        if core_mem:
            return core_mem + "\n\n" + result
        return result

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        """Queue background search for the next turn.

        P1-2: 最新查询覆盖语义 —— 旧线程存活时新查询被记录为
        _pending_query，旧线程完成后接力处理，保证注入的是最新查询结果。
        """
        if not query or len(query.strip()) < 3:
            return

        with self._prefetch_lock:
            self._pending_query = query
            if self._prefetch_thread and self._prefetch_thread.is_alive():
                return  # 旧线程会接力处理 _pending_query

            def _bg_search():
                while True:
                    with self._prefetch_lock:
                        q = self._pending_query
                        self._pending_query = ""
                    if not q:
                        break
                    try:
                        # E3: 自动注入仍走门控（skip_gate=False → 服务端不旁路）
                        self._last_prefetch_result = self._do_search(q, skip_gate=False)
                    except Exception as e:
                        logger.debug("baize background prefetch failed: %s", e)
                        self._last_prefetch_result = ""

            self._prefetch_thread = threading.Thread(
                target=_bg_search, daemon=True, name="baize-prefetch"
            )
            self._prefetch_thread.start()

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Write completed turn to baize with routing logic.
        
        Routing rules (白皮书 §3.2):
        - Technical config/events/topology → baize
        - User preferences/iron rules → USER.md (≤50 chars)
        - Lessons/experiences → baize (with【待验证】prefix)
        - Temporary observations → don't store
        """
        # Skip writes for non-primary contexts (cron, subagents)
        if self._agent_context != "primary":
            return
        
        if not user_content or len(user_content.strip()) < 5:
            return
        
        # Classify content type
        content_type = self._classify_content(user_content, assistant_content)
        
        # Route based on type
        if content_type == "temporary":
            # Don't store temporary observations
            return
        
        # Gate check: three questions (白皮书 §3.2)
        if not self._passes_gate(user_content, content_type):
            return
        
        if content_type == "preference":
            # Write to USER.md via memory tool (handled by Hermes built-in)
            # baize also stores for search
            self._write_to_baize(user_content, assistant_content, source="hermes_preference")
        elif content_type == "lesson":
            # Write to baize with【待验证】prefix
            self._write_to_baize(user_content, assistant_content, source="hermes_lesson")
        else:
            # Default: write to baize
            self._write_to_baize(user_content, assistant_content, source="hermes")

    def _classify_content(self, user_content: str, assistant_content: str = "") -> str:
        """Classify content type for routing.

        P0-1 修复：只基于用户消息判断（assistant 回复不参与，避免
        "我搜索了…"等表述误杀整轮）；临时观察用正则锚定匹配纯时效
        短语，不再子串匹配"现在/搜索/运行/执行"等高频词。
        """
        content = user_content.lower().strip()

        # 临时观察（不存储）：仅纯时效性一次性询问，锚定开头，不子串匹配
        temp_patterns = [
            r"^(现在|请问现在|帮我查一下)几点",
            r"今天几号",
            r"^(今天|明天|后天)(天气|气温|温度)",
            r"^今天星期",
            r"^(星期|周)[一二三四五六日天]$",
            r"^(好的?|收到|ok|嗯|知道了|明白|了解|没问题|可以|行)[。!！]?$",
        ]
        if any(re.search(p, content) for p in temp_patterns):
            return "temporary"

        # User preferences/iron rules
        pref_patterns = [
            "偏好", "喜欢", "不喜欢", "习惯", "规则",
            "铁律", "必须", "禁止", "不要",
            "称呼", "叫", "名字",
        ]
        if any(p in content for p in pref_patterns):
            return "preference"

        # Lessons/experiences
        lesson_patterns = [
            "教训", "踩坑", "错误", "失败", "问题",
            "解决", "修复", "排查", "原因",
            "经验", "总结", "复盘",
        ]
        if any(p in content for p in lesson_patterns):
            return "lesson"

        # Default: technical config/events
        return "technical"

    def _passes_gate(self, content: str, content_type: str) -> bool:
        """Three questions gate (白皮书 §3.2):
        1. Is this needed tomorrow? (temporary observations don't pass)
        2. Will it conflict with existing memories? (check for duplicates)
        3. Can it be compressed to 50 chars? (if not, route to baize)
        """
        # Question 1: Is this needed tomorrow?
        # Already handled by content_type == "temporary" check
        # For other types, assume they're needed
        
        # Question 2: Will it conflict with existing memories?
        # Check baize for similar content (async, non-blocking)
        if content_type in ["preference", "lesson"]:
            try:
                # Quick search for duplicates
                results = self._search(content[:50], limit=3)
                if results:
                    # Check if any result is very similar (score > 0.9)
                    for r in results:
                        if r.get("score", 0) > 0.9:
                            logger.debug("Gate: duplicate found, skipping")
                            return False
            except Exception:
                pass  # If search fails, allow write
        
        # Question 3: Can it be compressed to 50 chars?
        # If content is already short, it passes
        if len(content) <= 50:
            return True
        
        # For longer content, check if it's a preference that should be compressed
        if content_type == "preference":
            # Preferences should be short, compress or skip
            logger.debug("Gate: preference too long (%d chars), routing to baize", len(content))
            # Still allow write (will go to baize)
            return True
        
        # For technical/lesson content, allow longer entries
        return True

    def _write_to_baize(self, user_content: str, assistant_content: str = "",
                        source: str = "hermes") -> None:
        """Write to baize asynchronously."""
        # Build messages for baize /add
        msg_list = [
            {"role": "user", "content": user_content},
        ]
        if assistant_content:
            msg_list.append(
                {"role": "assistant", "content": assistant_content}
            )
        
        # Async write in background thread
        def _bg_write():
            try:
                self._add_memory(msg_list, source=source)
            except Exception as e:
                # E4: 不再静默丢弃——失败落盘 spool，由 _flush_spool 后台重试
                logger.debug("baize async write failed: %s", e)
                self._spool_write(msg_list, source)

        t = threading.Thread(target=_bg_write, daemon=True, name="baize-sync")
        t.start()

    # -- E4: 失败写入本地 spool 队列 + 后台重试 ---------------------------------

    def _spool_write(self, messages: List[Dict], source: str) -> None:
        """E4: HTTP 失败/超时数据落盘 spool（JSONL 一行一条），供 _flush_spool 重试。"""
        record = {"ts": time.time(), "messages": messages, "source": source}
        try:
            with open(self._spool_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("baize spool write failed: %s", e)

    def _flush_spool(self) -> None:
        """E4: 重试 spool 队列——成功逐条删除该行，失败保留；临时文件 + os.replace 原子替换。"""
        if not self._spool_path or not os.path.exists(self._spool_path):
            return
        try:
            with open(self._spool_path, encoding="utf-8") as f:
                lines = [ln for ln in f if ln.strip()]
        except Exception as e:
            logger.warning("baize spool read failed: %s", e)
            return

        kept = []
        flushed = 0
        for ln in lines:
            try:
                rec = json.loads(ln)
                self._add_memory(rec.get("messages", []), source=rec.get("source", "hermes"))
                flushed += 1
            except Exception as e:
                logger.debug("baize spool retry failed, keep line: %s", e)
                kept.append(ln)

        try:
            if kept:
                tmp = self._spool_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.writelines(kept)
                os.replace(tmp, self._spool_path)
            elif os.path.exists(self._spool_path):
                os.remove(self._spool_path)
        except Exception as e:
            logger.warning("baize spool flush write failed: %s", e)
        if flushed:
            logger.info("baize spool flushed %d records", flushed)

    def _spool_loop(self) -> None:
        """E4: daemon 线程，间隔 _spool_interval 秒重试 spool（仅在文件存在时工作）。"""
        while True:
            time.sleep(self._spool_interval)
            try:
                self._flush_spool()
            except Exception as e:
                logger.warning("baize spool flush loop error: %s", e)

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Expose baize tools to the model."""
        return [
            {
                "name": "baize_search",
                "description": "搜索 baize 长期记忆。用于查找过去的对话、用户偏好、重要事实等。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索关键词或问题",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "返回结果数量（默认5）",
                            "default": 5,
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "baize_add",
                "description": "手动写入一条长期记忆到 baize。用于重要事实、用户偏好等。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "要记住的内容（中文短句）",
                        },
                    },
                    "required": ["content"],
                },
            },
        ]

    def handle_tool_call(
        self, tool_name: str, args: Dict[str, Any], **kwargs
    ) -> str:
        """Handle baize tool calls."""
        if tool_name == "baize_search":
            query = args.get("query", "")
            limit = args.get("limit", _PREFETCH_LIMIT)
            # E3: 模型显式调用检索工具 = 明确检索意图，绕过服务端门控
            results = self._search(query, limit=limit, skip_gate=True)
            return json.dumps({"results": results}, ensure_ascii=False)
        
        elif tool_name == "baize_add":
            content = args.get("content", "")
            if not content:
                return json.dumps({"error": "content is required"})
            result = self._add_memory(
                [{"role": "user", "content": content}],
                source="hermes_manual",
                force_sync=True,
            )
            return json.dumps(result, ensure_ascii=False)
        
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def on_pre_compress(self, messages: List[Dict]) -> str:
        """压缩前归档钩子（压缩桥 L2，2026-08-07）。

        Hermes 压缩丢弃旧消息前调用本方法：把将被丢弃的对话文本与
        工具输出（规则式提取，零模型成本）写入白泽，返回痕迹字符串
        注入压缩摘要——压缩器不再凭空总结，归档留痕可追溯。

        借鉴 Letta 的 archival 机制：上下文压缩 = 归档到外部记忆，
        核心只留摘要；需要时经 baize 检索召回。
        """
        if not messages:
            return ""
        try:
            items, seen = [], set()
            # 只看将被压缩的部分（最近 60 条；protect_last_n 之外的更早消息）
            for m in messages[-60:]:
                role = m.get("role", "")
                content = m.get("content", "")
                if isinstance(content, list):  # OpenAI 消息格式
                    texts = [c.get("text", "") for c in content if isinstance(c, dict)]
                    content = "\n".join(t for t in texts if t)
                if not isinstance(content, str) or not content.strip():
                    continue
                text = content.strip().replace("\r", " ").replace("\n", " ")
                if role in ("user", "assistant"):
                    if len(text) > 300:
                        text = text[:300]
                elif role == "tool":
                    text = f"[tool:{m.get('name', 'output')}] " + (text[:200] if len(text) > 200 else text)
                else:
                    continue
                if text in seen:
                    continue
                seen.add(text)
                items.append({"content": text, "lane": "general", "source": "compression"})
                if len(items) >= 20:
                    break
            if not items:
                return ""
            payload = {
                "messages": json.dumps(items),
                "user_id": self._user_id,
                "metadata": {"source": "compression"},
            }
            req = urllib.request.Request(
                f"{self._base_url}/api/ingest",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            resp = json.loads(urllib.request.urlopen(req, timeout=8).read())
            n = resp.get("inserted", 0)
            if n <= 0:
                return ""
            return (f"[压缩归档] 本次压缩前已将 {n} 条关键信息写入白泽"
                    f"（source=compression），后续可用 baize 检索召回。")
        except Exception:
            return ""

    def shutdown(self) -> None:
        """Clean shutdown."""
        pass

    # -- Private helpers ----------------------------------------------------

    def _do_search(self, query: str, skip_gate: bool = True) -> str:
        """Search baize and format results for context injection.

        L1 缓存优化（2026-08-07）：结果按 (score desc, id asc) 稳定排序，
        输出去掉 score 前缀——注入块文本只取决于内容本身，不再随分数
        微抖而变，最大化 prompt 前缀缓存命中率。
        """
        results = self._search(query, limit=_PREFETCH_LIMIT, skip_gate=skip_gate)
        if not results:
            return ""
        # 稳定排序：同分按 id 升序，顺序跨请求可复现
        try:
            results = sorted(
                results,
                key=lambda r: (-float(r.get("score", 0) or 0), int(r.get("id", 0) or 0)),
            )
        except Exception:
            pass
        lines = ["[baize 相关记忆]"]
        for r in results:
            content = r.get("content", "").strip()
            if not content:
                continue
            # Truncate long results
            if len(content) > _PREFETCH_MAX_CHARS:
                content = content[:_PREFETCH_MAX_CHARS] + "..."
            lines.append(f"- {content}")

        return "\n".join(lines) if len(lines) > 1 else ""

    def _search(self, query: str, limit: int = 5,
                skip_gate: Optional[bool] = None) -> List[Dict]:
        """Call baize /search API.

        E3: skip_gate=True（显式检索意图，如模型调 baize_search 工具）时 body 带
        skip_gate 绕过服务端门控；自动注入路径（queue_prefetch）不传 → 仍走门控。
        """
        payload = {
            "query": query,
            "user_id": self._user_id,
            "limit": limit,
        }
        if skip_gate is not None:
            payload["skip_gate"] = skip_gate
        data = json.dumps(payload).encode("utf-8")
        
        try:
            req = urllib.request.Request(
                f"{self._base_url}/search",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=_PREFETCH_TIMEOUT)
            result = json.loads(resp.read())
            return result.get("results", [])
        except Exception as e:
            logger.debug("baize search failed: %s", e)
            return []

    def _add_memory(
        self,
        messages: List[Dict],
        source: str = "hermes",
        force_sync: bool = False,
    ) -> Dict:
        """Call baize /add API."""
        payload = {
            "messages": json.dumps(messages),
            "user_id": self._user_id,
            "metadata": {
                "source": source,
                "platform": self._platform,
            },
        }
        
        if force_sync:
            payload["metadata"]["force_sync"] = True
        else:
            payload["async_mode"] = True
        
        data = json.dumps(payload).encode("utf-8")
        
        try:
            req = urllib.request.Request(
                f"{self._base_url}/add",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=_ADD_TIMEOUT)
            return json.loads(resp.read())
        except Exception as e:
            logger.debug("baize add failed: %s", e)
            return {"error": str(e)}

    def _http_get(self, path: str) -> Dict:
        """Simple GET request to baize."""
        try:
            req = urllib.request.Request(f"{self._base_url}{path}")
            resp = urllib.request.urlopen(req, timeout=5)
            return json.loads(resp.read())
        except Exception as e:
            return {"error": str(e)}

    def _get_core_memory(self) -> str:
        """Get CoreMemory content for injection (P1-3: TTL 60s 缓存)."""
        now = time.time()
        if now - self._core_mem_cache["ts"] < self._CORE_MEM_TTL:
            return self._core_mem_cache["text"]
        result = ""
        try:
            req = urllib.request.Request(f"{self._base_url}/api/core-memory")
            resp = urllib.request.urlopen(req, timeout=3)
            data = json.loads(resp.read())
            blocks = data.get("blocks", {})
            parts = []
            for block_name, block_data in blocks.items():
                content = block_data.get("content", "").strip()
                if content:
                    label = {
                        "user_profile": "User Profile",
                        "current_project": "Current Project",
                        "key_decisions": "Key Decisions",
                    }.get(block_name, block_name)
                    parts.append(f"[{label}]\n{content}")
            if parts:
                result = "[CoreMemory]\n" + "\n\n".join(parts)
        except Exception as e:
            logger.debug("CoreMemory fetch failed: %s", e)
        self._core_mem_cache = {"ts": now, "text": result}
        return result


# Plugin entry point
def get_provider():
    """Factory function for MemoryManager."""
    return BaiZeProvider()
