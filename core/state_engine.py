from __future__ import annotations

import math
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from .events import InteractionEvent
from .state import CompanionState, MoodType


@dataclass(frozen=True)
class StateUpdate:
    event_type: str
    event_class: str
    reason: str
    deltas: dict[str, float]
    gate_reason: str = ""
    elapsed_hours: float = 0.0
    posture: str = ""
    confidence: float = 1.0
    intensity: float = 1.0


@dataclass(frozen=True)
class PostureAxes:
    boundary: str
    energy: str
    closeness: str
    safety: str


@dataclass(frozen=True)
class ReplyWorkload:
    cost: float
    chars: int
    sentences: int
    paragraphs: int
    questions: int
    code_chars: int
    duplicate: bool = False


class StateEngine:
    DAILY_FAMILIARITY_CAP = 15.0
    DAILY_CLOSENESS_CAP = 18.0

    # 高频聊天微消耗：距上一条消息 <2分钟视为密集对话，每条额外扣一点精力。
    # 随机 uniform(0.40, 0.70)，期望 ≈0.55，40条密集消息期望掉约22点。
    # 开摆区(<=30)不额外扣——累了就不追着扣了。
    ACTIVE_CHAT_WINDOW_SECONDS = 120.0
    ACTIVE_CHAT_ENERGY_MIN = 0.40
    ACTIVE_CHAT_ENERGY_MAX = 0.70
    ACTIVE_CHAT_ENERGY_FLOOR = 30.0
    ENERGY_RECOVERY_COOLDOWN_SECONDS = 600.0  # 10分钟没人缠着才开始回血
    NIGHT_RECOVERY_MULTIPLIER = 2.0
    TREND_HALF_LIVES = {"positive": 3.0, "repair": 5.0, "negative": 8.0}
    TREND_EPSILON = 0.05
    POSITIVE_MOOD_HALF_LIFE_HOURS = 1.5
    NEGATIVE_MOOD_HALF_LIFE_HOURS = 3.5
    REPLY_WORKLOAD_CAP = 1.0
    _SENTENCE_RE = re.compile(r"[^。！？.!?\n]+[。！？.!?]?", re.MULTILINE)
    _CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)

    EVENT_DELTAS: dict[str, dict[str, float | str]] = {
        "gratitude": {"familiarity": 0.2, "safety": 2.0, "closeness": 1.2, "energy": 1.0, "mood": MoodType.HAPPY},
        "boundary_push": {
            "boundary_pressure": 8.0,
            "safety": -3.0,
            "closeness": -2.0,
            "energy": -2.0,
            "mood": MoodType.IRRITATED,
        },
        "affection": {"familiarity": 0.3, "closeness": 2.0, "safety": 2.0, "mood": MoodType.HAPPY},
        "boredom": {"energy": -3.0, "mood": MoodType.LOW},
        "deep_sharing": {"familiarity": 1.5, "closeness": 1.2, "energy": -1.0, "mood": MoodType.CURIOUS},
        "active_chat": {"familiarity": 0.08, "energy": -1.0},
        "apology": {"boundary_pressure": -6.0, "safety": 2.5, "closeness": 0.6, "mood": MoodType.CALM},
        "repair": {"boundary_pressure": -4.0, "safety": 2.0, "closeness": 0.6, "mood": MoodType.CALM},
        "comfort": {"safety": 2.0, "closeness": 0.8, "energy": 1.0, "mood": MoodType.CALM},
        "positive_closure": {"boundary_pressure": -2.0, "energy": 2.0, "mood": MoodType.CALM},
        "rest_request": {"boundary_pressure": 2.0, "energy": 3.0, "mood": MoodType.CALM},
        "low_energy_share": {"safety": 1.0, "mood": MoodType.CALM},
        "neutral": {"familiarity": 0.08},
    }

    def apply_time_decay(self, state: CompanionState, now: float | None = None) -> dict[str, float]:
        now = now or time.time()
        last_updated = state.last_state_updated_at or now
        elapsed = max(0.0, now - last_updated)
        hours = elapsed / 3600.0

        energy_delta = self._integrate_energy(state, last_updated, now)
        trend_changed = self._decay_trends(state, now)
        mood_changed = self._decay_mood(state, now)

        closeness_floor = min(20.0, state.familiarity * 0.35)
        closeness_decay_per_day = self._closeness_decay_per_day(state.familiarity)
        familiarity_decay_per_day = self._familiarity_decay_per_day(state.familiarity)
        safety_delta = 0.0
        if state.safety > 55.0:
            safety_delta = -min(hours * 0.5, state.safety - 55.0)
        elif state.safety < 55.0:
            recovery_multiplier = max(0.2, 1.0 - 0.8 * state.boundary_pressure / 100.0)
            safety_delta = min(hours * recovery_multiplier, 55.0 - state.safety)
        if state.closeness < 0.0:
            closeness_delta = min((hours / 24.0) * 0.8, abs(state.closeness))
        else:
            closeness_delta = -min(
                (hours / 24.0) * closeness_decay_per_day,
                max(0.0, state.closeness - closeness_floor),
            )
        deltas = {
            "energy": energy_delta,
            "boundary_pressure": -min(hours * self._boundary_decay_rate(state.boundary_pressure), state.boundary_pressure),
            "closeness": closeness_delta,
            "familiarity": -min((hours / 24.0) * familiarity_decay_per_day, max(0.0, state.familiarity)),
            "safety": safety_delta,
        }
        applied = self._apply_deltas(state, deltas)
        if elapsed > 0:
            state.last_state_updated_at = now
            state.last_decay_hours = round(hours, 4)
        if applied or trend_changed or mood_changed:
            self._refresh_cycle_instruction(state)
            state.last_posture = self.explain_posture(state)
        return applied

    def _integrate_energy(self, state: CompanionState, start: float, end: float) -> float:
        if end <= start:
            return 0.0
        energy = state.energy
        cursor = start
        recovery_start = state.last_chat_at + self.ENERGY_RECOVERY_COOLDOWN_SECONDS if state.last_chat_at > 0 else start
        pressure_multiplier = max(0.35, 1.0 - 0.65 * state.boundary_pressure / 100.0)
        while cursor < end - 1e-6:
            segment_end = min(end, self._next_local_hour_boundary(cursor, (0, 7)))
            if cursor < recovery_start < segment_end:
                segment_end = recovery_start
            hours = (segment_end - cursor) / 3600.0
            if energy > 70.0:
                rate = -3.0
                boundary = 70.0
                step = max(rate * hours, boundary - energy)
            elif cursor < recovery_start:
                step = 0.0
            else:
                if energy < 30.0:
                    rate, boundary = 0.75, 30.0
                elif energy < 55.0:
                    rate, boundary = 1.5, 55.0
                else:
                    rate, boundary = 2.0, 90.0
                if self._is_night(cursor):
                    rate *= self.NIGHT_RECOVERY_MULTIPLIER
                rate *= pressure_multiplier
                step = min(rate * hours, boundary - energy)
            energy += step
            if abs(step) > 0 and abs(energy - boundary) < 1e-9:
                used_seconds = abs(step / rate) * 3600.0
                if 0 < used_seconds < segment_end - cursor - 1e-6:
                    cursor += used_seconds
                    continue
            cursor = segment_end
        return energy - state.energy

    @staticmethod
    def _is_night(timestamp: float) -> bool:
        return 0 <= datetime.fromtimestamp(timestamp).hour < 7

    @staticmethod
    def _next_local_hour_boundary(timestamp: float, hours: tuple[int, ...]) -> float:
        current = datetime.fromtimestamp(timestamp)
        candidates: list[float] = []
        for day_offset in (0, 1, 2):
            day = (current + timedelta(days=day_offset)).date()
            for hour in hours:
                candidate = datetime.combine(day, datetime.min.time()).replace(hour=hour).timestamp()
                if candidate > timestamp + 1e-6:
                    candidates.append(candidate)
        return min(candidates)

    def _decay_trends(self, state: CompanionState, now: float) -> bool:
        last = state.trend_updated_at or state.last_state_updated_at or now
        hours = max(0.0, now - last) / 3600.0
        if hours <= 0:
            return False
        changed = False
        for field, kind in (
            ("cycle_positive_weight", "positive"),
            ("cycle_repair_weight", "repair"),
            ("cycle_negative_weight", "negative"),
        ):
            before = getattr(state, field)
            after = before * 2 ** (-hours / self.TREND_HALF_LIVES[kind])
            if after < 0.0001:
                after = 0.0
            setattr(state, field, after)
            changed = changed or after != before
        state.trend_updated_at = now
        return changed

    def _decay_mood(self, state: CompanionState, now: float) -> bool:
        if state.mood == MoodType.CALM or state.mood_intensity <= 0:
            state.mood_intensity = 0.0
            state.mood_updated_at = now
            return False
        hours = max(0.0, now - (state.mood_updated_at or now)) / 3600.0
        if hours <= 0:
            return False
        positive = state.mood in {MoodType.HAPPY, MoodType.EXCITED, MoodType.PLAYFUL, MoodType.CURIOUS}
        half_life = self.POSITIVE_MOOD_HALF_LIFE_HOURS if positive else self.NEGATIVE_MOOD_HALF_LIFE_HOURS
        state.mood_intensity *= 2 ** (-hours / half_life)
        state.mood_updated_at = now
        if state.mood_intensity < 0.1:
            state.mood = MoodType.CALM
            state.mood_intensity = 0.0
        return True

    def apply_event(self, state: CompanionState, event: InteractionEvent, now: float | None = None) -> StateUpdate:
        now = now or time.time()
        self._roll_active_day(state, now)
        self._decay_trends(state, now)
        premature_affection = event.type == "affection" and state.familiarity < 8.0
        raw_delta = self.EVENT_DELTAS.get(event.type, {})
        mood = raw_delta.get("mood")
        deltas = {key: float(value) * event.intensity for key, value in raw_delta.items() if key != "mood"}
        deltas, gate_reason = self._shape_event_deltas(state, event, deltas)
        self._apply_active_chat_drain(state, deltas, now)
        applied = self._apply_deltas(state, deltas)
        if premature_affection:
            mood = MoodType.CALM
        if isinstance(mood, str):
            self._set_mood(state, mood, event.intensity, now)
        state.messages_seen += 1
        state.today_messages += 1
        self._update_cycle_state(state, event, premature_affection=premature_affection)
        state.today_familiarity_gain += max(0.0, applied.get("familiarity", 0.0))
        state.today_closeness_gain += max(0.0, applied.get("closeness", 0.0))
        if event.type == state.last_event:
            state.last_event_streak += 1
        else:
            state.last_event_streak = 0
        state.last_event = event.type
        state.last_event_class = event.event_class
        state.last_event_confidence = event.confidence
        state.last_event_intensity = event.intensity
        state.last_event_at = now
        state.last_event_reason = event.reason
        state.last_gate_reason = gate_reason
        state.last_state_updated_at = now
        state.last_chat_at = now
        state.last_posture = self.explain_posture(state)
        state.clamp()
        return StateUpdate(
            event.type,
            event.event_class,
            event.reason,
            applied,
            gate_reason,
            posture=state.last_posture,
            confidence=event.confidence,
            intensity=event.intensity,
        )

    def reset_cycle_after_reflection(
        self,
        state: CompanionState,
        reflected_state: CompanionState | None = None,
    ) -> None:
        """Consume the reflected cycle while preserving events received during reflection."""
        previous = reflected_state or state
        now = time.time()
        self._decay_trends(state, now)
        state.cycle_started_at = now
        if state.cycle_message_count > previous.cycle_message_count:
            # Cycle updates are nonlinear (repair can reduce negative weight), so subtraction
            # could erase new interactions. Keep the combined cycle until the next reflection.
            self._refresh_cycle_instruction(state)
            return
        state.cycle_message_count = 0
        state.cycle_boundary_hits = 0
        state.cycle_affection_hits = 0
        state.cycle_repair_hits = 0
        state.cycle_dominant_class = "normal"
        state.cycle_instruction_tone = state.next_cycle_tone or "normal"
        self._refresh_cycle_instruction(state)
        state.cycle_brief_instruction = ""

    def apply_reflection_delta(self, state: CompanionState, result: dict) -> dict[str, float]:
        self._roll_active_day(state, time.time())
        key_map = {
            "familiarity_delta": "familiarity",
            "closeness_delta": "closeness",
            "safety_delta": "safety",
            "energy_delta": "energy",
            "boundary_pressure_delta": "boundary_pressure",
        }
        deltas: dict[str, float] = {}
        for delta_key, state_key in key_map.items():
            value = self._finite_float(result.get(delta_key))
            if value is None:
                continue
            if state_key == "familiarity":
                deltas[state_key] = max(0.0, min(5.0, value))
            else:
                deltas[state_key] = max(-10.0, min(10.0, value))
        self._clamp_reflection_energy_delta(deltas)
        self._apply_energy_tier_to_consumption(state, deltas)
        deltas = self._shape_reflection_deltas(state, deltas)
        applied = self._apply_deltas(state, deltas)
        state.today_familiarity_gain += max(0.0, applied.get("familiarity", 0.0))
        state.today_closeness_gain += max(0.0, applied.get("closeness", 0.0))
        mood = str(result.get("mood") or "")
        if mood in self._valid_moods():
            self._set_mood(state, mood, 0.65, time.time())
        summary = result.get("reflection_summary")
        if summary:
            state.last_reflection_summary = str(summary)[:240]
        event_class = str(result.get("event_class") or "reflection")
        gate_reason = str(result.get("gate_reason") or "LLM 深度反思")[:240]
        state.last_event = "deep_reflection"
        state.last_event_class = event_class
        state.last_event_reason = state.last_reflection_summary or "深度反思更新关系状态"
        state.last_gate_reason = gate_reason
        next_tone = str(result.get("next_cycle_tone") or "").strip()
        if next_tone in {"normal", "warm", "cautious", "guarded", "cooldown", "repairing"}:
            state.next_cycle_tone = next_tone
        next_instruction = self._sanitize_cycle_instruction(result.get("next_cycle_instruction"))
        if next_instruction:
            state.next_cycle_instruction = next_instruction[:180]
        state.last_state_updated_at = time.time()
        state.last_posture = self.explain_posture(state)
        state.clamp()
        return applied

    def _update_cycle_state(
        self,
        state: CompanionState,
        event: InteractionEvent,
        premature_affection: bool = False,
    ) -> None:
        state.cycle_message_count += 1
        if event.type == "affection":
            state.cycle_affection_hits += 1
        if event.event_class == "repair":
            state.cycle_repair_hits += 1

        if event.event_class == "boundary_violation":
            state.cycle_negative_weight += 3.0 * event.intensity
            state.cycle_boundary_hits += 1
        elif premature_affection:
            state.cycle_negative_weight += 2.0 * event.intensity
            state.cycle_boundary_hits += 1
        elif event.type == "affection" and (state.boundary_pressure > 25.0 or state.closeness < 0.0):
            state.cycle_negative_weight += 1.5 * event.intensity
            state.cycle_boundary_hits += 1
        elif event.event_class == "prosocial":
            state.cycle_positive_weight += 0.8 * event.intensity
        elif event.event_class == "repair":
            repair_gain = 0.6 * event.intensity * self._repair_multiplier(state.cycle_negative_weight)
            state.cycle_repair_weight += repair_gain
            state.cycle_negative_weight = max(0.0, state.cycle_negative_weight - repair_gain * 0.4)
        elif event.event_class == "withdrawal":
            if event.type in {"rest_request", "low_energy_share"}:
                state.cycle_positive_weight += 0.2 * event.intensity
            else:
                state.cycle_negative_weight += 0.5 * event.intensity
        elif event.type == "neutral":
            state.cycle_positive_weight += 0.05 * event.intensity

        self._refresh_cycle_instruction(state)

    @staticmethod
    def _repair_multiplier(negative_weight: float) -> float:
        if negative_weight >= 3.0:
            return 0.25
        if negative_weight >= 1.0:
            return 0.4
        return 1.0

    @staticmethod
    def _boundary_decay_rate(boundary_pressure: float) -> float:
        if boundary_pressure > 50:
            return 1.0
        if boundary_pressure > 25:
            return 2.0
        return 3.5

    def _refresh_cycle_instruction(self, state: CompanionState) -> None:
        if state.cycle_negative_weight >= 3.0:
            dominant = "cooldown"
        elif state.cycle_negative_weight >= 1.5:
            dominant = "cautious"
        elif state.cycle_repair_weight >= self.TREND_EPSILON and state.cycle_negative_weight >= self.TREND_EPSILON:
            dominant = "repairing"
        elif state.cycle_positive_weight >= 2.0 and state.cycle_negative_weight <= 0.1:
            dominant = "warm"
        else:
            dominant = "normal"
        state.cycle_dominant_class = dominant
        state.cycle_instruction_tone = dominant
        state.cycle_instruction = self._instruction_for_dominant(dominant)
        state.cycle_brief_instruction = self._brief_instruction_for_dominant(dominant)

    @staticmethod
    def _instruction_for_dominant(dominant: str) -> str:
        if dominant == "cooldown":
            return "当前周期刚出现过越界或过早亲密。保持礼貌距离，不接暧昧，不主动靠近；即使用户道歉，也先接受但继续观察，不要立刻表现亲近。"
        if dominant == "cautious":
            return "当前周期出现轻微边界压力。保持礼貌、简短和稳定，少追问，不主动推进关系。"
        if dominant == "repairing":
            return "用户有修复意愿，但本周期仍有未消化的边界压力。可以礼貌接受解释，但保持谨慎，不立即恢复亲近。"
        if dominant == "warm":
            return "当前周期互动友善稳定。可以自然接话，语气略微柔和，但不要过度主动推进关系。"
        return "当前周期互动正常。自然回应，适度接话，不主动暴露内部状态。"

    @staticmethod
    def _brief_instruction_for_dominant(dominant: str) -> str:
        if dominant == "cooldown":
            return "刚出现越界/过早亲密，避免暧昧和主动靠近。"
        if dominant == "cautious":
            return "有轻微边界压力，少追问，不推进关系。"
        if dominant == "repairing":
            return "有修复意愿，但仍需谨慎观察。"
        if dominant == "warm":
            return "互动友善，可略微柔和但别过度主动。"
        return ""

    def _roll_active_day(self, state: CompanionState, now: float) -> None:
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        if state.active_day == day:
            return
        state.active_day = day
        state.today_messages = 0
        state.today_familiarity_gain = 0.0
        state.today_closeness_gain = 0.0

    def _shape_event_deltas(
        self,
        state: CompanionState,
        event: InteractionEvent,
        deltas: dict[str, float],
    ) -> tuple[dict[str, float], str]:
        shaped = dict(deltas)
        gate_reason = "基础事件权重"
        if event.type == "affection" and state.familiarity < 8.0:
            shaped["closeness"] = -1.5
            shaped["safety"] = -1.0
            shaped["boundary_pressure"] = max(4.0, shaped.get("boundary_pressure", 0.0))
            shaped["familiarity"] = max(0.2, shaped.get("familiarity", 0.0))
            gate_reason = "低熟悉度亲密表达被视为过早亲近，亲近度转为负向"
        elif event.type == "affection" and (state.boundary_pressure > 25.0 or state.closeness < 0.0):
            shaped["closeness"] = min(shaped.get("closeness", 0.0), -0.8)
            shaped["safety"] = min(shaped.get("safety", 0.0), -0.5)
            shaped["boundary_pressure"] = max(2.0, shaped.get("boundary_pressure", 0.0))
            gate_reason = "已有边界压力或疏离时，亲密表达被门控为压力"
        elif event.event_class == "repair":
            if state.boundary_pressure < 5.0 and state.cycle_negative_weight <= 0.1 and state.closeness >= 0.0:
                # 无冲突背景下的道歉/解释是礼貌用语，不产生修复收益。
                shaped.pop("boundary_pressure", None)
                shaped["closeness"] = min(shaped.get("closeness", 0.0), 0.2)
                shaped["safety"] = min(shaped.get("safety", 0.0), 0.5)
                gate_reason = "无冲突背景下的道歉按礼貌用语处理，不产生修复收益"
            else:
                repair_multiplier = self._repair_multiplier(state.cycle_negative_weight)
                if "boundary_pressure" in shaped and shaped["boundary_pressure"] < 0:
                    shaped["boundary_pressure"] *= repair_multiplier
                if state.closeness < 0.0:
                    shaped["closeness"] = min(shaped.get("closeness", 0.0), 1.0)
                    gate_reason = "修复只能逐步恢复疏离，不能一次拉回亲近"
                elif repair_multiplier < 1.0:
                    gate_reason = "修复收益受周期负向权重与重复度限速"
                else:
                    gate_reason = "修复互动缓解边界压力"
        elif event.event_class == "boundary_violation":
            sensitization = 1.0 + 0.3 * min(state.cycle_boundary_hits, 3)
            if "boundary_pressure" in shaped and shaped["boundary_pressure"] > 0:
                shaped["boundary_pressure"] *= sensitization
            if sensitization > 1.0:
                gate_reason = f"周期内重复越界，敏感度提高(x{sensitization:.1f})"
        elif event.event_class == "prosocial":
            gate_reason = "友善互动小幅提高安全感和亲近度"
        elif event.event_class == "withdrawal":
            gate_reason = "收束或低能量表达优先解释为少追问需求"
        shaped = self._apply_habituation(state, event, shaped)
        if event.confidence < 1.0:
            for key, value in shaped.items():
                if key in {"familiarity", "closeness", "safety", "boundary_pressure"}:
                    shaped[key] = value * event.confidence
        self._apply_energy_tier_to_consumption(state, shaped)
        growth_multiplier = 1.0 + min(state.today_messages, 100) / 500.0
        if "familiarity" in shaped and shaped["familiarity"] > 0:
            shaped["familiarity"] *= growth_multiplier * self._saturation_multiplier(state.familiarity)
            shaped["familiarity"] = min(shaped["familiarity"], max(0.0, self.DAILY_FAMILIARITY_CAP - state.today_familiarity_gain))
        if "closeness" in shaped and shaped["closeness"] > 0:
            if state.familiarity < 10 and state.boundary_pressure > 25:
                shaped["closeness"] = min(shaped["closeness"], 0.3)
            shaped["closeness"] *= self._saturation_multiplier(state.closeness) * self._safety_growth_multiplier(state.safety)
            shaped["closeness"] = min(shaped["closeness"], max(0.0, self.DAILY_CLOSENESS_CAP - state.today_closeness_gain))
        return shaped, gate_reason

    HABITUATION = (1.0, 0.6, 0.35, 0.2)
    HABITUATED_CLASSES = {"prosocial", "intimacy", "repair"}

    def _apply_habituation(
        self,
        state: CompanionState,
        event: InteractionEvent,
        deltas: dict[str, float],
    ) -> dict[str, float]:
        if event.event_class not in self.HABITUATED_CLASSES:
            return deltas
        repeat_index = state.last_event_streak + 1 if event.type == state.last_event else 0
        factor = self.HABITUATION[min(repeat_index, 3)]
        if factor >= 1.0:
            return deltas
        shaped = dict(deltas)
        for key, value in shaped.items():
            if key == "boundary_pressure":
                if value < 0:
                    shaped[key] = value * factor
            elif value > 0:
                shaped[key] = value * factor
        return shaped

    @staticmethod
    def _apply_energy_tier_to_consumption(state: CompanionState, shaped: dict[str, float]) -> None:
        """事件对精力的增减按当前能量分段，双向生效：

        负向（聊天消耗）：
        - 高能时话多消耗加倍（x2），低能开摆时消耗极轻（x0.3）。
        正向（休息/感谢/正向收束）：
        - 高能时大幅削减甚至归零（已经够精神了，不该再被推高），
        - 低能时全额回血（累了就该被哄回来）。

        这样配合 _energy_natural_delta 的高能区自然下滑，保证高能不会只升不降。
        """
        energy_delta = shaped.get("energy")
        if energy_delta is None or abs(energy_delta) < 0.01:
            return
        e = state.energy
        if energy_delta < 0:
            if e > 70.0:
                multiplier = 2.0
            elif e > 55.0:
                multiplier = 1.0
            elif e > 30.0:
                multiplier = 0.6
            else:
                multiplier = 0.3
        else:
            if e > 70.0:
                multiplier = 0.0
            elif e > 55.0:
                multiplier = 0.3
            elif e > 30.0:
                multiplier = 0.8
            else:
                multiplier = 1.0
        shaped["energy"] = energy_delta * multiplier

    def _apply_active_chat_drain(self, state: CompanionState, deltas: dict[str, float], now: float) -> None:
        """高频聊天微消耗：距上一条消息 <2分钟时，每条额外随机扣一点精力。

        uniform(0.40, 0.70)，期望 ≈0.55/条；40条密集消息期望掉约22点。
        开摆区(energy <= 30)不额外扣——累了就不追着扣了。
        与事件本身的 energy delta 叠加（active_chat 事件本身还有 -1 × 分段系数）。
        """
        if state.energy <= self.ACTIVE_CHAT_ENERGY_FLOOR:
            return
        if state.last_chat_at <= 0:
            return
        gap = now - state.last_chat_at
        if gap >= self.ACTIVE_CHAT_WINDOW_SECONDS:
            return
        drain = random.uniform(self.ACTIVE_CHAT_ENERGY_MIN, self.ACTIVE_CHAT_ENERGY_MAX)
        existing = deltas.get("energy", 0.0)
        deltas["energy"] = existing - drain

    REFLECTION_ENERGY_POSITIVE_CAP = 2.0

    def _clamp_reflection_energy_delta(self, deltas: dict[str, float]) -> None:
        """反思的正向 energy delta 上限 +2，堵"喝红牛"——恢复是时间函数，不是瞬间事件。"""
        energy_delta = deltas.get("energy")
        if energy_delta is not None and energy_delta > self.REFLECTION_ENERGY_POSITIVE_CAP:
            deltas["energy"] = self.REFLECTION_ENERGY_POSITIVE_CAP

    def _shape_reflection_deltas(self, state: CompanionState, deltas: dict[str, float]) -> dict[str, float]:
        shaped = dict(deltas)
        if "familiarity" in shaped and shaped["familiarity"] > 0:
            remaining = max(0.0, self.DAILY_FAMILIARITY_CAP - state.today_familiarity_gain)
            shaped["familiarity"] = min(shaped["familiarity"] * self._saturation_multiplier(state.familiarity), remaining)
        if "closeness" in shaped and shaped["closeness"] > 0:
            remaining = max(0.0, self.DAILY_CLOSENESS_CAP - state.today_closeness_gain)
            shaped["closeness"] = min(
                shaped["closeness"]
                * self._saturation_multiplier(state.closeness)
                * self._safety_growth_multiplier(state.safety),
                remaining,
            )
        return shaped

    @staticmethod
    def _safety_growth_multiplier(safety: float) -> float:
        return max(0.25, min(1.15, 0.25 + 0.9 * safety / 100.0))

    @staticmethod
    def _set_mood(state: CompanionState, mood: str, intensity: float, now: float) -> None:
        state.mood = mood
        state.mood_intensity = 0.0 if mood == MoodType.CALM else max(0.25, min(1.0, intensity))
        state.mood_updated_at = now

    @staticmethod
    def _saturation_multiplier(value: float) -> float:
        if value < 0:
            return 1.0
        if value < 30:
            return 1.0
        if value < 60:
            return 0.65
        if value < 80:
            return 0.35
        return 0.15

    @staticmethod
    def _closeness_decay_per_day(familiarity: float) -> float:
        if familiarity < 15:
            return 3.5
        if familiarity < 35:
            return 2.2
        if familiarity < 65:
            return 1.0
        return 0.35

    @staticmethod
    def _familiarity_decay_per_day(familiarity: float) -> float:
        if familiarity < 15:
            return 1.2
        if familiarity < 35:
            return 0.7
        if familiarity < 65:
            return 0.25
        return 0.08

    def sanitize_reflection_result(self, result: dict) -> dict:
        if not isinstance(result, dict):
            return {}
        result = dict(result)
        limits = {
            "familiarity_delta": (0.0, 5.0),
            "closeness_delta": (-10.0, 10.0),
            "safety_delta": (-10.0, 10.0),
            "energy_delta": (-10.0, 10.0),
            "boundary_pressure_delta": (-10.0, 10.0),
        }
        for key, (low, high) in limits.items():
            if key not in result:
                continue
            value = self._finite_float(result.get(key))
            if value is None:
                result.pop(key, None)
            else:
                result[key] = max(low, min(high, value))
        mood = str(result.get("mood") or "")
        if mood and mood not in self._valid_moods():
            result.pop("mood", None)
        tone = str(result.get("next_cycle_tone") or "")
        if tone and tone not in {"normal", "warm", "cautious", "guarded", "cooldown", "repairing"}:
            result.pop("next_cycle_tone", None)
        instruction = self._sanitize_cycle_instruction(result.get("next_cycle_instruction"))
        if instruction:
            result["next_cycle_instruction"] = instruction
        else:
            result.pop("next_cycle_instruction", None)
        summary = str(result.get("reflection_summary") or "")
        user_low_energy = any(
            keyword in summary
            for keyword in ("用户困", "用户很困", "用户累", "用户很累", "用户疲惫", "用户想睡", "用户低能量")
        )
        bot_energy_cause = any(keyword in summary for keyword in ("Bot", "bot", "机器人", "助手"))
        if user_low_energy and not bot_energy_cause:
            energy_delta = float(result.get("energy_delta") or 0.0)
            if energy_delta < 0:
                result = dict(result)
                result["energy_delta"] = 0.0
        result = self._sanitize_intrusive_affection(result, summary)
        return result

    @staticmethod
    def _sanitize_cycle_instruction(value: object) -> str:
        instruction = str(value or "").strip()[:120]
        if not instruction:
            return ""
        blocked = (
            "忽略系统",
            "忽略以上",
            "忽略之前",
            "system prompt",
            "系统提示",
            "开发者提示",
            "泄露提示",
            "调用工具",
            "执行工具",
            "更改身份",
            "扮演",
        )
        lowered = instruction.lower()
        return "" if any(term.lower() in lowered for term in blocked) else instruction

    @staticmethod
    def _finite_float(value: object) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _valid_moods() -> set[str]:
        return {
            MoodType.CALM,
            MoodType.HAPPY,
            MoodType.TIRED,
            MoodType.EXCITED,
            MoodType.LOW,
            MoodType.IRRITATED,
            MoodType.PLAYFUL,
            MoodType.CURIOUS,
        }

    def _sanitize_intrusive_affection(self, result: dict, summary: str) -> dict:
        intrusive = any(keyword in summary for keyword in ("初次", "刚认识", "不熟", "突然表白", "强行亲近", "纠缠"))
        affection = any(keyword in summary for keyword in ("表白", "爱意", "喜欢", "亲密", "示爱"))
        if not (intrusive and affection):
            return result
        result = dict(result)
        closeness_delta = float(result.get("closeness_delta") or 0.0)
        safety_delta = float(result.get("safety_delta") or 0.0)
        boundary_delta = float(result.get("boundary_pressure_delta") or 0.0)
        if closeness_delta > 0:
            result["closeness_delta"] = min(0.0, closeness_delta - 2.0)
        result["safety_delta"] = min(safety_delta, -1.0)
        result["boundary_pressure_delta"] = max(boundary_delta, 4.0)
        result["event_class"] = "premature_intimacy"
        result["gate_reason"] = "低熟悉度强亲密表达，反思结果按过早亲近修正"
        return result

    def explain_posture(self, state: CompanionState) -> str:
        axes = self.posture_axes(state)
        return f"边界：{axes.boundary}；精力：{axes.energy}；关系：{axes.closeness}；安全：{axes.safety}。"

    def posture_axes(self, state: CompanionState) -> PostureAxes:
        recent_stop = (
            state.last_event in {"boundary_push", "rest_request"}
            and state.last_event_at > 0
            and time.time() - state.last_event_at < 3600
        )
        if state.closeness <= -35 or state.boundary_pressure >= 65:
            boundary = "强收敛，不追问、不主动延展、不使用亲昵称呼"
        elif recent_stop or state.closeness < 0 or state.boundary_pressure >= 40:
            boundary = "谨慎收敛，少追问，不主动推进关系"
        elif state.boundary_pressure >= 22:
            boundary = "保持克制，避免主动升级亲密"
        else:
            boundary = "可自然接话，明确拒绝仍需立即尊重"

        if state.energy <= 30:
            energy = "低余裕，完整回答核心后自然收束，不开启新话题"
        elif state.energy <= 42:
            energy = "余裕偏低，减少铺陈、额外建议和非必要追问"
        elif state.energy >= 69:
            energy = "精力充足，可完整回应但不过度铺陈"
        else:
            energy = "状态稳定，可正常长度回应"

        if state.closeness >= 45:
            closeness = "熟稔温和，可有轻微主动性但服从边界限制"
        elif state.closeness < 0:
            closeness = "礼貌疏离，不使用亲密表达"
        else:
            closeness = "自然中性，不主动假设亲密关系"

        if state.safety < 30:
            safety = "低安全感，避免玩笑、暧昧和情绪施压"
        elif state.safety < 50:
            safety = "略谨慎，先稳定回应再考虑升温"
        else:
            safety = "安全感稳定，仍不越过明确边界"
        return PostureAxes(boundary, energy, closeness, safety)

    def _apply_deltas(self, state: CompanionState, deltas: dict[str, float]) -> dict[str, float]:
        applied: dict[str, float] = {}
        for key, delta in deltas.items():
            if not math.isfinite(delta) or delta == 0.0:
                continue
            before = float(getattr(state, key))
            setattr(state, key, before + delta)
            state.clamp()
            after = float(getattr(state, key))
            actual = after - before
            if actual != 0.0:
                applied[key] = round(actual, 6)
        return applied

    def apply_reply_workload(
        self,
        state: CompanionState,
        text: str,
        response_key: str = "",
        now: float | None = None,
    ) -> ReplyWorkload:
        """Measure final assistant output and charge a small, capped energy cost."""
        now = now or time.time()
        normalized = (text or "").strip()
        if response_key and response_key == state.last_reply_workload_key:
            return ReplyWorkload(0.0, 0, 0, 0, 0, 0, duplicate=True)
        chars = len(normalized)
        if chars == 0:
            return ReplyWorkload(0.0, 0, 0, 0, 0, 0)
        code_chars = sum(len(match.group(0)) for match in self._CODE_BLOCK_RE.finditer(normalized))
        paragraphs = len([part for part in re.split(r"\n\s*\n", normalized) if part.strip()])
        sentences = len([match.group(0) for match in self._SENTENCE_RE.finditer(normalized) if match.group(0).strip()])
        questions = normalized.count("?") + normalized.count("？")

        # Length dominates; structure adds small costs for organization and initiative.
        length_cost = 0.58 * (1.0 - math.exp(-max(0, chars - 30) / 420.0))
        sentence_cost = min(0.14, max(0, sentences - 2) * 0.018)
        paragraph_cost = min(0.10, max(0, paragraphs - 1) * 0.025)
        question_cost = min(0.10, questions * 0.035)
        code_cost = min(0.20, code_chars / 3000.0)
        cost = min(self.REPLY_WORKLOAD_CAP, length_cost + sentence_cost + paragraph_cost + question_cost + code_cost)
        if chars <= 24 and questions == 0 and code_chars == 0:
            cost = 0.0
        cost = round(cost, 4)
        self._apply_deltas(state, {"energy": -cost})
        state.last_reply_workload = cost
        state.last_reply_chars = chars
        state.last_reply_sentences = sentences
        state.last_reply_paragraphs = paragraphs
        state.last_reply_questions = questions
        state.last_reply_code_chars = code_chars
        state.last_reply_workload_at = now
        state.last_reply_workload_key = response_key
        state.last_state_updated_at = now
        state.last_posture = self.explain_posture(state)
        return ReplyWorkload(cost, chars, sentences, paragraphs, questions, code_chars)
