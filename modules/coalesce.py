"""Wave Coalesce - batch short messages before LLM extraction."""
import time
import threading
import logging
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field

log = logging.getLogger("baize.coalesce")

PROFILES = {
    "tech":     {"idle_sec": 2.5, "window_sec": 8,  "max_parts": 6,  "max_chars": 1500, "tail_chars": 300, "head_chars": 200},
    "default":  {"idle_sec": 4.0, "window_sec": 12, "max_parts": 8,  "max_chars": 2000, "tail_chars": 300, "head_chars": 200},
    "intimate": {"idle_sec": 8.0, "window_sec": 20, "max_parts": 12, "max_chars": 3000, "tail_chars": 300, "head_chars": 200},
}

# Budget reserved for the injected trim delimiter/label when head is elided.
_TRIM_OVERHEAD = 13  # len("\n...[前序内容省略]\n")


@dataclass
class WaveBuffer:
    messages: List[str] = field(default_factory=list)
    first_time: float = 0
    last_time: float = 0
    profile: str = "default"
    user_id: str = "default"


def _smart_trim(text: str, max_chars: int, head_chars: int, tail_chars: int) -> str:
    """Trim combined wave text while preserving conclusion at the tail.

    Strategy:
    - If text is within budget, return as-is.
    - If not, keep tail_chars at the end (conclusion / last sentence) and
      head_chars at the beginning (context/background), separated by an
      elision marker.  The LLM extraction prompt can still infer the full
      picture from the two fragments plus the marker.
    - If even head+tail+overhead does not fit, fall back to a plain tail
      window so we never exceed max_chars.
    """
    if not text or len(text) <= max_chars:
        return text

    # Try head + tail first.
    budget = max_chars - _TRIM_OVERHEAD
    if head_chars + tail_chars <= budget:
        head = text[:head_chars]
        tail = text[-tail_chars:] if tail_chars else ""
        trimmed = head + "\n...[前序内容省略]\n" + tail
        if len(trimmed) <= max_chars:
            return trimmed

    # Fallback: tail-only window to honor the budget strictly.
    return text[-max_chars:]


class CoalesceManager:
    """Manages wave coalescing for message batching."""

    def __init__(self, flush_callback: Optional[Callable] = None):
        self._buffers: Dict[str, WaveBuffer] = {}
        self._lock = threading.Lock()
        self._flush_callback = flush_callback
        self._stats = {"waves": 0, "messages": 0, "saved_llm": 0}

    def add_message(self, user_id: str, session_id: str, message: str,
                    profile: str = "default") -> Dict:
        buf_key = f"{user_id}::{session_id}::{profile}"
        now = time.time()
        flush_data = None
        with self._lock:
            if buf_key not in self._buffers:
                self._buffers[buf_key] = WaveBuffer(first_time=now, profile=profile,
                                                    user_id=user_id)
            buf = self._buffers[buf_key]
            buf.messages.append(message)
            buf.last_time = now
            p = PROFILES.get(profile, PROFILES["default"])
            total_chars = sum(len(m) for m in buf.messages)
            if len(buf.messages) >= p["max_parts"] or total_chars >= p["max_chars"]:
                flush_data = self._pop_flush_data(buf_key)
        # Fire callback OUTSIDE the lock to avoid blocking concurrent
        # add_message() / check_idle_flush() calls during LLM extraction.
        if flush_data:
            self._fire_callback(flush_data)
            return flush_data
        log.info("coalesce_buffered: key=%s size=%d profile=%s",
                 buf_key, len(buf.messages), profile)
        return {"action": "coalesce_buffered", "buffer_size": len(buf.messages)}

    def check_idle_flush(self) -> List[Dict]:
        """Flush buffers whose idle time or window exceeds the profile threshold.

        Returns list of flushed buffer data. Callbacks are fired outside the lock
        so that LLM extraction in the callback does not block concurrent operations.
        """
        flush_list = []
        now = time.time()
        with self._lock:
            for key in list(self._buffers.keys()):
                buf = self._buffers[key]
                p = PROFILES.get(buf.profile, PROFILES["default"])
                idle = now - buf.last_time
                window = now - buf.first_time
                if idle >= p["idle_sec"] or window >= p["window_sec"]:
                    result = self._pop_flush_data(key)
                    if result["action"] == "wave_flushed":
                        log.info("check_idle_flush 触发: key=%s idle=%.1fs window=%.1fs "
                                 "idle_sec=%s window_sec=%s msgs=%d",
                                 key, idle, window, p["idle_sec"], p["window_sec"],
                                 result["count"])
                        flush_list.append(result)
                    else:
                        log.debug("check_idle_flush pop empty: key=%s", key)
        # Fire all callbacks outside the lock
        for result in flush_list:
            self._fire_callback(result)
        return flush_list

    def _pop_flush_data(self, buf_key: str) -> Dict:
        """Pop buffer and return flush data. Called with self._lock held.

        Unlike the old _flush_locked, this does NOT call the callback —
        the caller is responsible for that after releasing the lock.

        Tail-preserving trim: combined text is capped to profile max_chars
        while keeping the conclusion at the end and a short head for context.
        """
        buf = self._buffers.pop(buf_key, None)
        if not buf or not buf.messages:
            return {"action": "empty"}
        messages = buf.messages[:]
        profile = buf.profile
        p = PROFILES.get(profile, PROFILES["default"])
        combined = "\n".join(messages)
        max_chars = p.get("max_chars", 2000)
        if len(combined) > max_chars:
            head_chars = p.get("head_chars", 200)
            tail_chars = p.get("tail_chars", 300)
            trimmed = _smart_trim(combined, max_chars, head_chars, tail_chars)
            messages = [trimmed]
            log.info("coalesce_trim: profile=%s before=%d after=%d reason=max_chars",
                     profile, len(combined), len(trimmed))
        self._stats["waves"] += 1
        self._stats["messages"] += len(messages)
        if len(messages) > 1:
            self._stats["saved_llm"] += len(messages) - 1
        return {
            "action": "wave_flushed",
            "messages": messages,
            "count": len(messages),
            "profile": profile,
            "trimmed": len(combined) > max_chars,
            "user_id": buf.user_id,
        }

    def _fire_callback(self, result: Dict) -> None:
        """Call the flush callback for a wave_flushed result. Lock is NOT held."""
        if result.get("action") == "wave_flushed" and self._flush_callback:
            try:
                self._flush_callback(result["messages"], result["profile"],
                                     result.get("user_id", "default"))
            except Exception as e:
                log.error("Flush callback 失败: %s", e)

    def get_buffered_count(self) -> int:
        """Number of active buffers."""
        return len(self._buffers)

    def get_stats(self) -> Dict:
        stats = self._stats.copy()
        total = stats["messages"]
        saved = stats["saved_llm"]
        stats["llm_save_rate"] = round(saved / total, 3) if total > 0 else 0
        stats["avg_per_wave"] = round(total / stats["waves"], 1) if stats["waves"] > 0 else 0
        stats["buffered_count"] = len(self._buffers)
        return stats
