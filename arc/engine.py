from __future__ import annotations

import time
from typing import Any

from ..core.state import CompanionState
from ..core.storage import Storage


class ArcEngine:
    """Structured session arcs and evidence-based interaction profile."""

    SESSION_IDLE_SECONDS = 60 * 60
    MAX_TURNING_POINTS = 12
    CONTINUITY_MAX = 220
    OUTCOME_TEXT = {
        "stable_warm": "上次会话稳定友善",
        "stable_neutral": "上次会话整体平稳",
        "warming": "上次会话逐渐升温",
        "cooling": "上次会话有所降温",
        "boundary_escalation": "上次会话出现明显边界压力",
        "unresolved_tension": "上次会话仍有未消化的紧张",
        "partial_repair": "上次会话出现修复意愿，但尚未完全恢复",
        "recovered": "上次会话从紧张中逐步恢复",
        "energy_exhaustion": "上次会话后段精力偏低",
        "mixed": "上次会话有明显拉扯",
    }

    def __init__(self, storage: Storage, lookback_sessions: int = 7) -> None:
        self._storage = storage
        self._lookback_sessions = max(3, min(20, lookback_sessions))

    @staticmethod
    def state_snapshot(state: CompanionState) -> dict[str, float]:
        return {
            "familiarity": round(state.familiarity, 4),
            "closeness": round(state.closeness, 4),
            "safety": round(state.safety, 4),
            "boundary_pressure": round(state.boundary_pressure, 4),
            "energy": round(state.energy, 4),
            "negative_trend": round(state.cycle_negative_weight, 4),
            "positive_trend": round(state.cycle_positive_weight, 4),
            "repair_trend": round(state.cycle_repair_weight, 4),
        }

    def record_event(
        self,
        user_id: str,
        before: dict[str, float],
        state: CompanionState,
        event: Any,
        applied_deltas: dict[str, float],
        now: float | None = None,
    ) -> dict[str, Any]:
        now = now or time.time()
        arc = self._ensure_open_session(user_id, before, now)
        after = self.state_snapshot(state)
        arc["last_activity_at"] = now
        arc["end_snapshot"] = after
        arc["message_count"] = int(arc.get("message_count", 0)) + 1
        arc["peak_boundary_pressure"] = max(float(arc.get("peak_boundary_pressure", 0)), after["boundary_pressure"])
        arc["peak_negative_trend"] = max(float(arc.get("peak_negative_trend", 0)), after["negative_trend"])
        arc["peak_positive_trend"] = max(float(arc.get("peak_positive_trend", 0)), after["positive_trend"])
        arc["min_energy"] = min(float(arc.get("min_energy", 90)), after["energy"])
        point = self._turning_point(before, after, event, applied_deltas, now)
        if point:
            arc["turning_points"] = self._merge_turning_point(arc.get("turning_points", []), point)
        self._storage.update_session_arc(int(arc["id"]), arc)
        return arc

    def record_reply(self, user_id: str, state: CompanionState, now: float | None = None) -> None:
        now = now or time.time()
        arc = self._storage.get_open_session_arc(user_id)
        if not arc:
            return
        arc["last_activity_at"] = now
        arc["end_snapshot"] = self.state_snapshot(state)
        arc["min_energy"] = min(float(arc.get("min_energy", 90)), state.energy)
        self._storage.update_session_arc(int(arc["id"]), arc)

    def update_session_from_reflection(self, user_id: str, result: dict[str, Any]) -> None:
        arc = self._storage.get_open_session_arc(user_id)
        if not arc:
            return
        summary = str(result.get("reflection_summary") or "").strip()
        if summary:
            arc["summary"] = summary[:240]
        arc["reflection_count"] = int(arc.get("reflection_count", 0)) + 1
        self._storage.update_session_arc(int(arc["id"]), arc)

    def close_idle_session(self, user_id: str, state: CompanionState, now: float | None = None) -> dict[str, Any] | None:
        now = now or time.time()
        arc = self._storage.get_open_session_arc(user_id)
        if not arc or now - float(arc.get("last_activity_at", now)) < self.SESSION_IDLE_SECONDS:
            return None
        return self._close_session(arc, state, now)

    def _ensure_open_session(self, user_id: str, snapshot: dict[str, float], now: float) -> dict[str, Any]:
        arc = self._storage.get_open_session_arc(user_id)
        if arc and now - float(arc.get("last_activity_at", now)) >= self.SESSION_IDLE_SECONDS:
            self._close_session_from_snapshot(arc, snapshot, float(arc.get("last_activity_at", now)))
            arc = None
        return arc or self._storage.create_session_arc(user_id, snapshot, now)

    def _close_session(self, arc: dict[str, Any], state: CompanionState, now: float) -> dict[str, Any]:
        arc["end_snapshot"] = self.state_snapshot(state)
        return self._finalize_arc(arc, now)

    def _close_session_from_snapshot(self, arc: dict[str, Any], snapshot: dict[str, float], now: float) -> dict[str, Any]:
        arc["end_snapshot"] = dict(snapshot)
        return self._finalize_arc(arc, now)

    def _finalize_arc(self, arc: dict[str, Any], now: float) -> dict[str, Any]:
        arc["status"] = "closed"
        arc["ended_at"] = now
        arc["last_activity_at"] = min(now, float(arc.get("last_activity_at", now)))
        arc["outcome"] = self._classify_outcome(arc)
        self._storage.update_session_arc(int(arc["id"]), arc)
        return arc

    @classmethod
    def _turning_point(
        cls,
        before: dict[str, float],
        after: dict[str, float],
        event: Any,
        applied: dict[str, float],
        now: float,
    ) -> dict[str, Any] | None:
        event_type = str(getattr(event, "type", "neutral"))
        event_class = str(getattr(event, "event_class", "neutral"))
        if event_class == "boundary_violation" or after["boundary_pressure"] - before["boundary_pressure"] >= 5:
            kind = "boundary_escalation"
        elif event_class == "repair" and before["boundary_pressure"] >= 5:
            kind = "repair_attempt"
        elif before["positive_trend"] < 2 <= after["positive_trend"]:
            kind = "warming"
        elif before["energy"] > 42 >= after["energy"]:
            kind = "energy_drop"
        elif before["energy"] <= 42 < after["energy"]:
            kind = "energy_recovery"
        elif abs(after["closeness"] - before["closeness"]) >= 2 or abs(after["safety"] - before["safety"]) >= 3:
            kind = "relationship_shift"
        else:
            return None
        posture = "cautious" if after["boundary_pressure"] >= 22 or after["closeness"] < 0 else "normal"
        return {
            "at": now,
            "kind": kind,
            "event_type": event_type,
            "event_class": event_class,
            "intensity": round(float(getattr(event, "intensity", 1.0)), 3),
            "reason": str(getattr(event, "reason", ""))[:120],
            "changes": {key: round(value, 4) for key, value in applied.items()},
            "posture": posture,
        }

    @classmethod
    def _merge_turning_point(cls, points: list[dict[str, Any]], point: dict[str, Any]) -> list[dict[str, Any]]:
        points = list(points)
        if points and points[-1].get("kind") == point["kind"] and point["at"] - float(points[-1].get("at", 0)) < 300:
            points[-1] = point
        else:
            points.append(point)
        return points[-cls.MAX_TURNING_POINTS :]

    @staticmethod
    def _classify_outcome(arc: dict[str, Any]) -> str:
        start = arc.get("start_snapshot", {})
        end = arc.get("end_snapshot", {})
        kinds = [point.get("kind") for point in arc.get("turning_points", [])]
        closeness_delta = float(end.get("closeness", 0)) - float(start.get("closeness", 0))
        pressure_end = float(end.get("boundary_pressure", 0))
        pressure_peak = float(arc.get("peak_boundary_pressure", pressure_end))
        if float(arc.get("min_energy", 90)) <= 30:
            return "energy_exhaustion"
        if "boundary_escalation" in kinds:
            if "repair_attempt" in kinds:
                return "recovered" if pressure_end <= max(8.0, pressure_peak * 0.45) else "partial_repair"
            return "unresolved_tension" if pressure_end >= 15 else "boundary_escalation"
        if closeness_delta >= 3:
            return "warming"
        if closeness_delta <= -3:
            return "cooling"
        if float(arc.get("peak_positive_trend", 0)) >= 2 and pressure_peak < 15:
            return "stable_warm"
        if float(arc.get("peak_negative_trend", 0)) >= 1 and float(arc.get("peak_positive_trend", 0)) >= 1:
            return "mixed"
        return "stable_neutral"

    def record_explicit_profile(self, user_id: str, event_type: str, now: float | None = None) -> None:
        mapping = {
            "style_length_short": ("reply_length", "short"),
            "style_length_long": ("reply_length", "long"),
            "style_tone_soft": ("tone", "soft"),
            "style_tone_direct": ("tone", "direct"),
            "rest_request": ("follow_up_questions", "avoid"),
        }
        mapped = mapping.get(event_type)
        if not mapped:
            return
        now = now or time.time()
        key, value = mapped
        existing = {item["profile_key"]: item for item in self._storage.get_profile_evidence(user_id)}.get(key)
        first_observed = float(existing.get("first_observed_at", now)) if existing else now
        positive = int(existing.get("positive_evidence", 0)) + 1 if existing and existing.get("profile_value") == value else 1
        self._storage.upsert_profile_evidence(
            user_id,
            {
                "key": key,
                "value": value,
                "source": "explicit",
                "positive_evidence": positive,
                "negative_evidence": 0,
                "confidence": 1.0,
                "first_observed_at": first_observed,
                "last_observed_at": now,
                "active": True,
            },
        )

    def build_continuity_text(self, user_id: str, cycle_dominant: str = "normal") -> str:
        arcs = self._storage.get_recent_session_arcs(user_id, limit=self._lookback_sessions, closed_only=True)
        parts: list[str] = []
        if arcs:
            latest = arcs[0]
            outcome = str(latest.get("outcome") or "stable_neutral")
            parts.append(self.OUTCOME_TEXT.get(outcome, "上次会话整体平稳") + "。")
            if outcome in {"boundary_escalation", "unresolved_tension", "partial_repair", "mixed"}:
                parts.append("本次先保持克制，少追问，不主动推进关系。")
            elif outcome == "recovered":
                parts.append("可以自然回应，但让恢复继续由稳定互动确认。")
            elif outcome in {"warming", "stable_warm"} and cycle_dominant not in {"cooldown", "cautious"}:
                parts.append("可以略微温和，但不越过当前边界。")
            outcomes = [str(arc.get("outcome") or "") for arc in arcs]
            tense = {"boundary_escalation", "unresolved_tension", "partial_repair", "mixed"}
            if sum(item in tense for item in outcomes) >= 2:
                parts.append("近期边界压力反复出现，避免主动升级亲密。")
        profile_text = self.build_profile_text(user_id)
        if profile_text:
            parts.append(profile_text)
        return "".join(parts)[: self.CONTINUITY_MAX]

    def build_session_brief(self, user_id: str) -> str:
        arc = self._storage.get_open_session_arc(user_id)
        if not arc:
            return ""
        kinds = [str(point.get("kind") or "") for point in arc.get("turning_points", [])]
        parts = [f"当前会话已记录{arc.get('message_count', 0)}条用户消息"]
        if kinds:
            parts.append("转折:" + ",".join(kinds[-4:]))
        parts.append(f"边界峰值{float(arc.get('peak_boundary_pressure', 0)):.0f}")
        return "会话轨迹：" + "，".join(parts) + "。"

    def build_profile_text(self, user_id: str) -> str:
        evidence = [
            item
            for item in self._storage.get_profile_evidence(user_id)
            if item.get("active") and float(item.get("confidence", 0)) >= 0.8
        ]
        labels = {
            ("reply_length", "short"): "用户明确偏好简短回复",
            ("reply_length", "long"): "用户明确偏好详细回复",
            ("tone", "soft"): "用户明确偏好温和语气",
            ("tone", "direct"): "用户明确偏好直接表达",
            ("follow_up_questions", "avoid"): "用户明确希望少追问",
        }
        parts = [labels.get((item["profile_key"], item["profile_value"]), "") for item in evidence]
        parts = [part for part in parts if part]
        return "；".join(parts[:2]) + "。" if parts else ""

    def get_open_session(self, user_id: str) -> dict | None:
        return self._storage.get_open_session_arc(user_id)

    def get_recent_sessions(self, user_id: str, limit: int = 7) -> list[dict]:
        return self._storage.get_recent_session_arcs(user_id, limit=limit)

    def get_interaction_profile(self, user_id: str) -> list[dict]:
        return self._storage.get_profile_evidence(user_id)
