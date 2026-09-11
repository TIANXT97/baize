"""Decay Manager - layered decay with zero-decay for identity/preference."""
import math
import time
from typing import Optional

LANE_CONFIG = {
    "identity":    {"multiplier": 0.0},
    "preference":  {"multiplier": 0.0},
    "secret":      {"multiplier": 0.0},
    "procedural":  {"multiplier": 0.3},
    "rule":        {"multiplier": 0.5},
    "lesson":      {"multiplier": 0.5},
    "evidence":    {"multiplier": 0.7},
    "knowledge":   {"multiplier": 1.0},
    "emotion":     {"multiplier": 1.5},
    "general":     {"multiplier": 1.0},
}

LAMBDA = 0.01  # ~69天半衰期


class DecayManager:
    """Calculate decay scores for memories based on their lane."""

    # E1: 暴露 LANE_CONFIG 供 api_server 判断 category 是否合法（实例属性引用模块常量）
    LANE_CONFIG = LANE_CONFIG

    def get_score(self, lane, created_at, access_count=0, importance=0.5, confirm_count=0):
        config = LANE_CONFIG.get(lane, LANE_CONFIG["general"])
        if config["multiplier"] == 0.0:
            # P2b: 零衰减轨道（identity/preference/secret）按被确认次数追加置信度 boost，
            # 封顶 0.2（confirm_count×0.05），总分上限提高到 0.95 让反复确认的
            # 偏好可超过普通 0.8 基线。普通轨道不加 boost 避免过度加权。
            # secret lane 锁死 1.0，不随次数变化，避免泄露访问模式
            if lane == "secret":
                return 1.0
            confirm_boost = min(0.2, confirm_count * 0.05)
            return min(0.95, max(0.8, importance) + confirm_boost)
        age_days = (time.time() - created_at) / 86400
        decay = math.exp(-LAMBDA * config["multiplier"] * age_days)
        access_boost = min(0.2, access_count * 0.02)
        score = importance * decay + access_boost
        return max(0.0, min(1.0, score))

    def evolve_importance(self, importance, access_count):
        """F1: 高频记忆 importance 微升（封顶 0.9）。access_count 每 10 次 +0.05。

        幂等：importance 为当前存储值（已内含此前 boost），先按上一次累计次数
        回推基值，再按新 access_count 重算 total boost——检索每命中一次都调用，
        不会重复累加，importance 只在新里程碑（10/20/30…）处提升一档。
        """
        if access_count <= 0:
            return importance
        prev_boost = min(0.4, ((access_count - 1) // 10) * 0.05)
        base = importance - prev_boost
        new_boost = min(0.4, (access_count // 10) * 0.05)
        return min(0.9, base + new_boost)

    def should_archive(self, lane: str, created_at: float,
                       threshold: float = 0.1, importance: float = 0.5,
                       access_count: int = 0) -> bool:
        score = self.get_score(lane, created_at, access_count=access_count,
                               importance=importance)
        return score < threshold

    def classify_lane(self, content, category="general"):
        if category in LANE_CONFIG:
            return category

        identity_kw = ["我叫", "我是", "名字", "生日", "住在", "工作", "职业"]
        preference_kw = ["喜欢", "不喜欢", "偏好", "习惯", "爱好", "最爱"]
        emotion_kw = ["开心", "难过", "生气", "焦虑", "兴奋", "失望", "心情"]
        procedural_kw = ["步骤", "配置", "执行", "操作", "流程", "方法"]
        rule_kw = ["必须", "禁止", "铁律", "底线", "规则", "不要"]
        lesson_kw = ["踩坑", "报错", "修复", "教训", "经验", "总结"]
        evidence_kw = ["发现", "测试", "验证", "确认", "证明"]
        knowledge_kw = ["API", "版本", "路径", "地址", "端口", "技术"]

        for kw in identity_kw:
            if kw in content: return "identity"
        for kw in preference_kw:
            if kw in content: return "preference"
        for kw in rule_kw:
            if kw in content: return "rule"
        for kw in lesson_kw:
            if kw in content: return "lesson"
        for kw in procedural_kw:
            if kw in content: return "procedural"
        for kw in evidence_kw:
            if kw in content: return "evidence"
        for kw in knowledge_kw:
            if kw in content: return "knowledge"
        for kw in emotion_kw:
            if kw in content: return "emotion"
        return "general"
