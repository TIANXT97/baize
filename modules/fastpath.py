"""Fast Path - pattern-based fact extraction that skips LLM."""
import re
from typing import Optional, Dict

FAST_PATTERNS = [
    (r"我叫(.{1,20})", "identity", "identity", 1),
    (r"我是(.{1,20}?)(?:[，。,.]|$)", "identity", "identity", 1),
    (r"我的名字是(.{1,20})", "identity", "identity", 1),
    (r"我住在(.{1,50})", "identity", "identity", 1),
    (r"我在(.{2,20})(?:工作|上班|居住)", "identity", "identity", 1),
    (r"我的生日是(.{1,20})", "identity", "identity", 1),
    (r"我喜欢(.{1,50}?)(?:[，。,.]|$)", "preference", "preference", 1),
    (r"我不喜欢(.{1,50}?)(?:[，。,.]|$)", "preference", "preference", 1),
    (r"我偏好(.{1,50}?)(?:[，。,.]|$)", "preference", "preference", 1),
    (r"我习惯(.{1,50}?)(?:[，。,.]|$)", "preference", "preference", 1),
]


class FastPath:
    """Extract simple facts without LLM, ~1s response time."""

    def try_extract(self, message: str) -> Optional[Dict]:
        msg = message.strip()
        if not msg or len(msg) > 200:
            return None
        for pattern, category, lane, group in FAST_PATTERNS:
            m = re.search(pattern, msg)
            if m:
                value = m.group(group).strip() if group else m.group(0).strip()
                fact = m.group(0).strip()
                if len(fact) < 3:
                    continue
                # Normalize to third person to match LLM extractor output
                fact = fact.replace("我", "用户")
                return {
                    "fact": fact,
                    "category": category,
                    "lane": lane,
                    "importance": 0.8 if lane == "identity" else 0.6,
                    "source": "fastpath",
                }
        return None
