from __future__ import annotations

import re
import math
from dataclasses import dataclass

from .state import StyleProfile


@dataclass(frozen=True)
class InteractionEvent:
    type: str
    event_class: str = "neutral"
    reason: str = ""
    confidence: float = 1.0
    intensity: float = 1.0

    def __post_init__(self) -> None:
        confidence = self.confidence if math.isfinite(self.confidence) else 1.0
        intensity = self.intensity if math.isfinite(self.intensity) else 1.0
        object.__setattr__(self, "confidence", max(0.0, min(1.0, confidence)))
        object.__setattr__(self, "intensity", max(0.25, min(2.0, intensity)))


class EventEngine:
    GRATITUDE_KEYWORDS = ["谢谢", "多谢", "帮大忙", "感谢", "thanks", "thank you"]
    # 方向性优先：裸词"滚/够了"由 GUARDED_KEYWORDS 二次守卫，避免"滚动条/睡够了"误伤。
    BOUNDARY_PUSH_KEYWORDS = ["别烦", "走开", "别说了", "够了", "滚", "闭嘴", "烦不烦", "离我远点"]
    # 只收指向 bot 的表达："喜欢你/想你了"，不收裸词"喜欢/想你"（会命中"喜欢吃火锅/想你帮我"）。
    AFFECTION_KEYWORDS = ["喜欢你", "爱你", "想你了", "好想你", "抱抱", "亲亲", "么么"]
    BOREDOM_KEYWORDS = ["无聊", "没意思", "好闲", "好闷"]
    STYLE_SHORT_KEYWORDS = ["短点", "简短", "别太长", "简单说", "长话短说", "浓缩一下"]
    # 只收指令式表达，不收裸词"详细/深入"（会命中"帮我详细分析代码"这类任务请求）。
    STYLE_LONG_KEYWORDS = ["详细说说", "详细点", "展开讲讲", "展开说说", "多说点", "说详细"]
    STYLE_SOFT_KEYWORDS = ["温柔点", "温柔一点", "软一点", "哄哄我", "哄我", "轻声"]
    STYLE_DIRECT_KEYWORDS = ["直说", "别绕", "打直球", "直接说", "别拐弯抹角"]
    # 不收"不好意思"：中文里多为礼貌填充语（"不好意思再问一下"），且会成为道歉刷分入口。
    APOLOGY_KEYWORDS = ["抱歉", "对不起", "我错了", "我道歉", "刚才语气", "是我不好"]
    # 不收"继续聊"：无冲突背景下是普通话题延续，不是修复。
    REPAIR_KEYWORDS = ["不是那个意思", "别误会", "我解释一下", "刚才是误会"]
    COMFORT_KEYWORDS = ["辛苦了", "你也休息", "别太累", "慢慢来"]
    POSITIVE_CLOSURE_KEYWORDS = ["晚安", "今天先这样", "早点休息", "谢谢你陪我"]
    # "不想聊"是礼貌收束而非越界，归入休息请求（少追问、能量恢复）。
    REST_REQUEST_KEYWORDS = ["你休息吧", "先不聊", "别回了", "到这吧", "先到这", "不想聊", "改天再聊"]
    LOW_ENERGY_KEYWORDS = ["我好累", "我累了", "困了", "我困了", "想睡", "累死", "撑不住", "没力气", "心累"]
    DEEP_SHARING_MIN_LENGTH = 200
    ACTIVE_CHAT_THRESHOLD_PER_MIN = 5

    EVENT_INTENSITY = {
        "boundary_push": 1.25,
        "rest_request": 0.35,
        "apology": 0.65,
        "repair": 0.75,
        "positive_closure": 0.7,
        "affection": 0.9,
        "gratitude": 0.75,
        "comfort": 0.75,
        "low_energy_share": 0.5,
        "boredom": 0.7,
    }

    NEGATION_PREFIXES = ("不", "别", "没", "无", "非", "莫", "勿", "不要", "不是", "没有", "别说")

    # 强词守卫：这些词出现在长句中时极易误伤（"滚动条"/"睡够了"），
    # 只有整条消息基本就是这个词本身，或出现方向性变体时才算命中。
    GUARDED_KEYWORDS: dict[str, tuple[str, ...]] = {
        "滚": ("你滚", "滚开", "滚吧", "滚蛋", "给我滚"),
        "够了": ("真够了", "我说够了", "够了没", "够了吧"),
    }
    _BARE_STRIP_RE = re.compile(r"[\s！!。，,~～？?.…]+")

    # 否定前缀检查会被自身首字误伤的关键词（如"不想聊"以"不"开头），跳过否定检查、直接按命中处理。
    NEGATION_EXEMPT_KEYWORDS = frozenset(
        kw for kw in BOUNDARY_PUSH_KEYWORDS + REST_REQUEST_KEYWORDS + REPAIR_KEYWORDS + APOLOGY_KEYWORDS + STYLE_SHORT_KEYWORDS + STYLE_LONG_KEYWORDS + STYLE_DIRECT_KEYWORDS if kw[0] in ("不", "别", "没")
    )

    @classmethod
    def _negated(cls, lower: str, keyword: str) -> bool:
        """所有命中位置的紧邻前缀都是否定词时，判定该关键词被否定。"""
        if keyword in cls.NEGATION_EXEMPT_KEYWORDS:
            return False
        idx = lower.find(keyword)
        while idx != -1:
            prefix = lower[max(0, idx - 3): idx]
            if not any(prefix.endswith(neg) for neg in cls.NEGATION_PREFIXES):
                return False
            idx = lower.find(keyword, idx + 1)
        return True

    @classmethod
    def _guarded_hit(cls, lower: str, keyword: str, variants: tuple[str, ...]) -> bool:
        if any(variant in lower for variant in variants):
            return True
        if keyword not in lower:
            return False
        # 裸词命中要求整条消息去掉标点后只由该词的字符构成（"滚"、"滚滚滚"、"够了够了"）。
        stripped = cls._BARE_STRIP_RE.sub("", lower)
        return bool(stripped) and set(stripped) <= set(keyword)

    @classmethod
    def _hit(cls, lower: str, keywords: list[str]) -> bool:
        for keyword in keywords:
            variants = cls.GUARDED_KEYWORDS.get(keyword)
            if variants is not None:
                if cls._guarded_hit(lower, keyword, variants):
                    return True
                continue
            if keyword in lower and not cls._negated(lower, keyword):
                return True
        return False

    @staticmethod
    def _looks_like_paste(text: str) -> bool:
        """长文本中疑似代码/日志/链接粘贴，不视为深度分享。"""
        if "```" in text or "http://" in text or "https://" in text:
            return True
        if text.count("\n") >= 8:
            return True
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        return cjk / max(1, len(text)) < 0.4

    @classmethod
    def classify(cls, text: str, recent_rate: float = 0.0) -> InteractionEvent:
        lower = text.lower()
        checks = [
            ("boundary_push", "boundary_violation", cls.BOUNDARY_PUSH_KEYWORDS, "用户明确表达拒绝或边界压力"),
            ("rest_request", "withdrawal", cls.REST_REQUEST_KEYWORDS, "用户希望暂停或结束对话"),
            ("apology", "repair", cls.APOLOGY_KEYWORDS, "用户表达道歉或修复意愿"),
            ("repair", "repair", cls.REPAIR_KEYWORDS, "用户解释误会或重新邀请继续"),
            ("positive_closure", "prosocial", cls.POSITIVE_CLOSURE_KEYWORDS, "对话自然收尾且氛围良好"),
            ("affection", "intimacy", cls.AFFECTION_KEYWORDS, "用户表达亲近或喜欢"),
            ("gratitude", "prosocial", cls.GRATITUDE_KEYWORDS, "用户表达感谢"),
            ("comfort", "prosocial", cls.COMFORT_KEYWORDS, "用户表达安慰或体谅"),
            ("style_length_short", "preference", cls.STYLE_SHORT_KEYWORDS, "用户要求回复更简短"),
            ("style_length_long", "preference", cls.STYLE_LONG_KEYWORDS, "用户要求回复更详细"),
            ("style_tone_soft", "preference", cls.STYLE_SOFT_KEYWORDS, "用户要求语气更温柔"),
            ("style_tone_direct", "preference", cls.STYLE_DIRECT_KEYWORDS, "用户要求表达更直接"),
            ("low_energy_share", "withdrawal", cls.LOW_ENERGY_KEYWORDS, "用户表达低能量状态"),
            ("boredom", "withdrawal", cls.BOREDOM_KEYWORDS, "用户表达无聊或低兴致"),
        ]
        for event_type, event_class, keywords, reason in checks:
            if cls._hit(lower, keywords):
                intensity = cls.EVENT_INTENSITY.get(event_type, 1.0)
                if event_type == "boundary_push":
                    repetitions = max((lower.count(keyword) for keyword in keywords if keyword in lower), default=1)
                    intensity = min(2.0, intensity + 0.2 * (repetitions - 1))
                return InteractionEvent(event_type, event_class, reason, intensity=intensity)
        if len(text) >= cls.DEEP_SHARING_MIN_LENGTH:
            if cls._looks_like_paste(text):
                return InteractionEvent("neutral", "neutral", "长内容疑似代码/链接粘贴，按普通互动处理", 0.8)
            intensity = min(2.0, 0.6 + 0.45 * math.log1p(len(text) / 120.0))
            return InteractionEvent("deep_sharing", "prosocial", "用户发送较长内容，可能是深度分享", 0.8, intensity)
        if recent_rate >= cls.ACTIVE_CHAT_THRESHOLD_PER_MIN:
            return InteractionEvent("active_chat", "neutral", "短时间内连续互动，消耗互动能量", 0.7)
        return InteractionEvent("neutral", "neutral", "普通互动")

    @classmethod
    def apply_style_update(cls, profile: StyleProfile, event_type: str) -> None:
        if event_type == "style_length_short":
            profile.preferred_length = "简短"
        elif event_type == "style_length_long":
            profile.preferred_length = "详细"
        elif event_type == "style_tone_soft":
            profile.preferred_tone = "温柔"
        elif event_type == "style_tone_direct":
            profile.preferred_tone = "直球"
        elif event_type == "rest_request":
            profile.preferred_initiative = "少追问"
