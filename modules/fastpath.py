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
    """Extract simple facts without LLM, ~1s response time.
    
    Qwen 3.8 Max 加固版：输入防爆、支持 group 捕获组提取、保守代词替换防污染。
    """

    def try_extract(self, message: str) -> Optional[Dict]:
        if not isinstance(message, str):
            return None
        msg = message[:8192].strip()
        if not msg or len(msg) > 500:
            return None

        candidates = []
        for idx, (pattern, category, lane, group) in enumerate(FAST_PATTERNS):
            try:
                m = re.search(pattern, msg)
            except Exception:
                continue

            if m:
                # 保持原样完整短事实，并只对句首的主谓语做第三人称化
                raw = m.group(0).strip()
                fact = (raw or "").strip()
                if len(fact) < 2:
                    continue

                # Qwen 3.8 Max 补丁：保守规范化，仅对以“我”开头的句首代词替换，保护“我们/我方”
                if fact.startswith("我的"):
                    fact = "用户的" + fact[2:]
                elif fact.startswith("我"):
                    fact = "用户" + fact[1:]

                importance = 0.8 if lane == "identity" else 0.6
                candidates.append({
                    "fact": fact,
                    "category": category,
                    "lane": lane,
                    "importance": importance,
                    "source": "fastpath",
                })

        if not candidates:
            return None

        # 优先返回 identity 身份事实，其次按重要性
        candidates.sort(key=lambda x: (x["lane"] == "identity", x["importance"]), reverse=True)
        return candidates[0]
