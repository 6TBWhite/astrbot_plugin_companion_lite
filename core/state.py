from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


class MoodType:
    CALM = "平静"
    HAPPY = "开心"
    TIRED = "疲惫"
    EXCITED = "兴奋"
    LOW = "低落"
    IRRITATED = "烦躁"
    PLAYFUL = "活泼"
    CURIOUS = "好奇"


class BoundaryStance:
    RELAXED = "放松"
    NORMAL = "正常"
    CAUTIOUS = "谨慎"
    DEFENSIVE = "防御"
    STRONG = "强边界"


@dataclass
class CompanionState:
    user_id: str
    familiarity: float = 0.0
    closeness: float = 0.0
    safety: float = 55.0
    boundary_pressure: float = 0.0
    mood: str = MoodType.CALM
    mood_intensity: float = 0.0
    mood_updated_at: float = field(default_factory=time.time)
    energy: float = 60.0
    messages_seen: int = 0
    last_event: str = "初始状态"
    last_event_reason: str = ""
    last_event_streak: int = 0
    last_state_updated_at: float = field(default_factory=time.time)
    last_chat_at: float = 0.0
    last_reflection_summary: str = ""
    last_posture: str = "稳定自然：正常回应，适度接话，不暴露内部状态。"
    last_event_class: str = "neutral"
    last_event_confidence: float = 1.0
    last_event_intensity: float = 1.0
    last_event_at: float = 0.0
    last_reply_workload: float = 0.0
    last_reply_chars: int = 0
    last_reply_sentences: int = 0
    last_reply_paragraphs: int = 0
    last_reply_questions: int = 0
    last_reply_code_chars: int = 0
    last_reply_workload_at: float = 0.0
    last_reply_workload_key: str = ""
    last_gate_reason: str = ""
    last_decay_hours: float = 0.0
    last_deep_reflection_at: float = 0.0
    active_day: str = ""
    today_messages: int = 0
    today_familiarity_gain: float = 0.0
    today_closeness_gain: float = 0.0
    bonded: bool = False
    cycle_started_at: float = field(default_factory=time.time)
    cycle_message_count: int = 0
    cycle_negative_weight: float = 0.0
    cycle_positive_weight: float = 0.0
    cycle_repair_weight: float = 0.0
    trend_updated_at: float = field(default_factory=time.time)
    cycle_boundary_hits: int = 0
    cycle_affection_hits: int = 0
    cycle_repair_hits: int = 0
    cycle_dominant_class: str = "normal"
    cycle_instruction: str = "当前周期互动正常。自然回应，适度接话，不主动暴露内部状态。"
    cycle_instruction_tone: str = "normal"
    cycle_brief_instruction: str = ""
    next_cycle_instruction: str = ""
    next_cycle_tone: str = "normal"

    def clamp(self) -> None:
        self.familiarity = max(0.0, min(100.0, self.familiarity))
        self.closeness = max(-50.0, min(100.0, self.closeness))
        self.safety = max(0.0, min(100.0, self.safety))
        self.boundary_pressure = max(0.0, min(100.0, self.boundary_pressure))
        self.energy = max(10.0, min(90.0, self.energy))
        self.mood_intensity = max(0.0, min(1.0, self.mood_intensity))

    def relationship_label(self) -> str:
        if self.closeness <= -35:
            return "强排斥"
        if self.closeness < 0:
            return "疏离"
        if self.boundary_pressure >= 65:
            return "防御"
        if self.boundary_pressure >= 40:
            return "紧张"
        if self.closeness >= 70 and self.boundary_pressure < 15:
            return "亲近"
        if self.familiarity >= 55:
            return "熟人"
        if self.familiarity >= 25:
            return "认识"
        return "刚认识"

    def boundary_stance(self) -> str:
        if self.closeness <= -35:
            return BoundaryStance.STRONG
        if self.closeness < 0:
            return BoundaryStance.DEFENSIVE
        if self.boundary_pressure >= 65:
            return BoundaryStance.STRONG
        if self.boundary_pressure >= 40:
            return BoundaryStance.DEFENSIVE
        if self.boundary_pressure >= 22:
            return BoundaryStance.CAUTIOUS
        if self.closeness >= 45 and self.boundary_pressure < 10:
            return BoundaryStance.RELAXED
        return BoundaryStance.NORMAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            # Keep integration precision in storage; commands and WebUI format for display.
            "familiarity": round(self.familiarity, 4),
            "closeness": round(self.closeness, 4),
            "safety": round(self.safety, 4),
            "boundary_pressure": round(self.boundary_pressure, 4),
            "mood": self.mood,
            "mood_intensity": round(self.mood_intensity, 4),
            "mood_updated_at": self.mood_updated_at,
            "energy": round(self.energy, 4),
            "messages_seen": self.messages_seen,
            "last_event": self.last_event,
            "last_event_reason": self.last_event_reason,
            "last_event_streak": self.last_event_streak,
            "last_state_updated_at": self.last_state_updated_at,
            "last_chat_at": self.last_chat_at,
            "last_reflection_summary": self.last_reflection_summary,
            "last_posture": self.last_posture,
            "last_event_class": self.last_event_class,
            "last_event_confidence": round(self.last_event_confidence, 4),
            "last_event_intensity": round(self.last_event_intensity, 4),
            "last_event_at": self.last_event_at,
            "last_reply_workload": round(self.last_reply_workload, 4),
            "last_reply_chars": self.last_reply_chars,
            "last_reply_sentences": self.last_reply_sentences,
            "last_reply_paragraphs": self.last_reply_paragraphs,
            "last_reply_questions": self.last_reply_questions,
            "last_reply_code_chars": self.last_reply_code_chars,
            "last_reply_workload_at": self.last_reply_workload_at,
            "last_reply_workload_key": self.last_reply_workload_key,
            "last_gate_reason": self.last_gate_reason,
            "last_decay_hours": self.last_decay_hours,
            "last_deep_reflection_at": self.last_deep_reflection_at,
            "active_day": self.active_day,
            "today_messages": self.today_messages,
            "today_familiarity_gain": round(self.today_familiarity_gain, 2),
            "today_closeness_gain": round(self.today_closeness_gain, 2),
            "bonded": self.bonded,
            "cycle_started_at": self.cycle_started_at,
            "cycle_message_count": self.cycle_message_count,
            "cycle_negative_weight": round(self.cycle_negative_weight, 4),
            "cycle_positive_weight": round(self.cycle_positive_weight, 4),
            "cycle_repair_weight": round(self.cycle_repair_weight, 4),
            "trend_updated_at": self.trend_updated_at,
            "cycle_boundary_hits": self.cycle_boundary_hits,
            "cycle_affection_hits": self.cycle_affection_hits,
            "cycle_repair_hits": self.cycle_repair_hits,
            "cycle_dominant_class": self.cycle_dominant_class,
            "cycle_instruction": self.cycle_instruction,
            "cycle_instruction_tone": self.cycle_instruction_tone,
            "cycle_brief_instruction": self.cycle_brief_instruction,
            "next_cycle_instruction": self.next_cycle_instruction,
            "next_cycle_tone": self.next_cycle_tone,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CompanionState:
        return cls(
            user_id=data.get("user_id", ""),
            familiarity=float(data.get("familiarity", 0.0)),
            closeness=float(data.get("closeness", 0.0)),
            safety=float(data.get("safety", 55.0)),
            boundary_pressure=float(data.get("boundary_pressure", 0.0)),
            mood=data.get("mood", MoodType.CALM),
            mood_intensity=float(data.get("mood_intensity", 0.0 if data.get("mood", MoodType.CALM) == MoodType.CALM else 1.0)),
            mood_updated_at=float(data.get("mood_updated_at", data.get("last_state_updated_at", time.time()))),
            energy=float(data.get("energy", 60.0)),
            messages_seen=int(data.get("messages_seen", 0)),
            last_event=data.get("last_event", "初始状态"),
            last_event_reason=data.get("last_event_reason", ""),
            last_event_streak=int(data.get("last_event_streak", 0)),
            last_state_updated_at=float(data.get("last_state_updated_at", data.get("updated_at", time.time()))),
            last_chat_at=float(data.get("last_chat_at", 0.0)),
            last_reflection_summary=data.get("last_reflection_summary", ""),
            last_posture=data.get("last_posture", "稳定自然：正常回应，适度接话，不暴露内部状态。"),
            last_event_class=data.get("last_event_class", "neutral"),
            last_event_confidence=float(data.get("last_event_confidence", 1.0)),
            last_event_intensity=float(data.get("last_event_intensity", 1.0)),
            last_event_at=float(data.get("last_event_at", data.get("last_chat_at", 0.0))),
            last_reply_workload=float(data.get("last_reply_workload", 0.0)),
            last_reply_chars=int(data.get("last_reply_chars", 0)),
            last_reply_sentences=int(data.get("last_reply_sentences", 0)),
            last_reply_paragraphs=int(data.get("last_reply_paragraphs", 0)),
            last_reply_questions=int(data.get("last_reply_questions", 0)),
            last_reply_code_chars=int(data.get("last_reply_code_chars", 0)),
            last_reply_workload_at=float(data.get("last_reply_workload_at", 0.0)),
            last_reply_workload_key=str(data.get("last_reply_workload_key", "")),
            last_gate_reason=data.get("last_gate_reason", ""),
            last_decay_hours=float(data.get("last_decay_hours", 0.0)),
            last_deep_reflection_at=float(data.get("last_deep_reflection_at", 0.0)),
            active_day=data.get("active_day", ""),
            today_messages=int(data.get("today_messages", 0)),
            today_familiarity_gain=float(data.get("today_familiarity_gain", 0.0)),
            today_closeness_gain=float(data.get("today_closeness_gain", 0.0)),
            bonded=bool(data.get("bonded", False)),
            cycle_started_at=float(data.get("cycle_started_at", time.time())),
            cycle_message_count=int(data.get("cycle_message_count", 0)),
            cycle_negative_weight=float(data.get("cycle_negative_weight", 0.0)),
            cycle_positive_weight=float(data.get("cycle_positive_weight", 0.0)),
            cycle_repair_weight=float(data.get("cycle_repair_weight", 0.0)),
            trend_updated_at=float(
                data.get("trend_updated_at", data.get("last_state_updated_at", data.get("cycle_started_at", time.time())))
            ),
            cycle_boundary_hits=int(data.get("cycle_boundary_hits", 0)),
            cycle_affection_hits=int(data.get("cycle_affection_hits", 0)),
            cycle_repair_hits=int(data.get("cycle_repair_hits", 0)),
            cycle_dominant_class=data.get("cycle_dominant_class", "normal"),
            cycle_instruction=data.get(
                "cycle_instruction", "当前周期互动正常。自然回应，适度接话，不主动暴露内部状态。"
            ),
            cycle_instruction_tone=data.get("cycle_instruction_tone", "normal"),
            cycle_brief_instruction=data.get("cycle_brief_instruction", ""),
            next_cycle_instruction=data.get("next_cycle_instruction", ""),
            next_cycle_tone=data.get("next_cycle_tone", "normal"),
        )


@dataclass
class StyleProfile:
    user_id: str
    preferred_length: str = "中等"
    preferred_tone: str = "自然"
    preferred_initiative: str = "正常接话"
    emotion_intensity: float = 0.5
    formality: float = 0.5
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "preferred_length": self.preferred_length,
            "preferred_tone": self.preferred_tone,
            "preferred_initiative": self.preferred_initiative,
            "emotion_intensity": round(self.emotion_intensity, 2),
            "formality": round(self.formality, 2),
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StyleProfile:
        return cls(
            user_id=data.get("user_id", ""),
            preferred_length=data.get("preferred_length", "中等"),
            preferred_tone=data.get("preferred_tone", "自然"),
            preferred_initiative=data.get("preferred_initiative", "正常接话"),
            emotion_intensity=float(data.get("emotion_intensity", 0.5)),
            formality=float(data.get("formality", 0.5)),
            updated_at=float(data.get("updated_at", time.time())),
        )
