from __future__ import annotations

import random
import time
from dataclasses import dataclass

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

        # 能量非线性演化不受 hours < 0.05 防抖门槛限制：
        # 高频聊天时恰恰是"活跃消耗"最该生效的场景，否则能量会被冻住。
        energy_delta = self._energy_natural_delta(state.energy, hours)
        if energy_delta > 0 and state.boundary_pressure > 60:
            energy_delta *= 0.5
        # 活跃聊天期间暂停自然回血——你在聊天不在休息，不该边聊边回血。
        # 用 10 分钟冷却期：哪怕中间停了几分钟，只要还没静下来够久就不回血。
        chat_gap = now - (state.last_state_updated_at or now)
        if energy_delta > 0 and chat_gap < self.ENERGY_RECOVERY_COOLDOWN_SECONDS:
            energy_delta = 0.0

        # 其余衰减保持防抖门槛，避免短间隔反复微小调整。
        if hours < 0.05:
            applied = self._apply_deltas(state, {"energy": energy_delta}) if energy_delta else {}
            if applied:
                state.last_event = "time_decay"
                state.last_event_reason = "随时间自然演化能量"
                state.last_state_updated_at = now
                state.last_decay_hours = round(hours, 4)
            return applied

        closeness_floor = min(20.0, state.familiarity * 0.35)
        closeness_decay_per_day = self._closeness_decay_per_day(state.familiarity)
        familiarity_decay_per_day = self._familiarity_decay_per_day(state.familiarity)
        safety_delta = 0.0
        if state.safety > 55.0:
            safety_delta = -min(hours * 0.5, state.safety - 55.0)
        elif state.safety < 55.0 and state.boundary_pressure < 35.0:
            safety_delta = min(hours * 1.0, 55.0 - state.safety)
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
        if applied:
            state.last_event = "time_decay"
            state.last_event_reason = "随时间自然演化能量、降低边界压力；未被重复强化的熟悉度和亲近度自然衰减"
            state.last_state_updated_at = now
            state.last_decay_hours = round(hours, 2)
        return applied

    @staticmethod
    def _energy_natural_delta(current_energy: float, hours: float) -> float:
        """非线性能量演化：高能消耗快，低能开摆稳态掉得慢。

        四段：
        - >70  高能区：精神好但活跃消耗大，朝 65 自然下滑（-3/h）
        - 55-70 中高区：稳态微恢复（+2/h，target 70）
        - 30-55 中低区：开始累，慢恢复（+1.5/h，target 55）
        - <30  开摆区：几乎持平，恢复极慢（+0.5/h，target 30）
        """
        e = current_energy
        if e > 70.0:
            raw = -hours * 3.0
            target = 65.0
        elif e > 55.0:
            raw = hours * 2.0
            target = 70.0
        elif e > 30.0:
            raw = hours * 1.5
            target = 55.0
        else:
            raw = hours * 0.5
            target = 30.0
        if raw > 0.0:
            return min(raw, max(0.0, target - e))
        if raw < 0.0:
            return max(raw, min(0.0, target - e))
        return 0.0

    def apply_event(self, state: CompanionState, event: InteractionEvent, now: float | None = None) -> StateUpdate:
        now = now or time.time()
        self._roll_active_day(state, now)
        raw_delta = self.EVENT_DELTAS.get(event.type, {})
        mood = raw_delta.get("mood")
        deltas = {key: float(value) for key, value in raw_delta.items() if key != "mood"}
        deltas, gate_reason = self._shape_event_deltas(state, event, deltas)
        self._apply_active_chat_drain(state, deltas, now)
        applied = self._apply_deltas(state, deltas)
        if event.type == "affection" and state.familiarity < 8.0:
            mood = MoodType.CALM
        if isinstance(mood, str):
            state.mood = mood
        state.messages_seen += 1
        state.today_messages += 1
        self._update_cycle_state(state, event)
        state.today_familiarity_gain += max(0.0, applied.get("familiarity", 0.0))
        state.today_closeness_gain += max(0.0, applied.get("closeness", 0.0))
        if event.type == state.last_event:
            state.last_event_streak += 1
        else:
            state.last_event_streak = 0
        state.last_event = event.type
        state.last_event_class = event.event_class
        state.last_event_reason = event.reason
        state.last_gate_reason = gate_reason
        state.last_state_updated_at = now
        state.last_posture = self.explain_posture(state)
        state.clamp()
        return StateUpdate(event.type, event.event_class, event.reason, applied, gate_reason, posture=state.last_posture)

    def reset_cycle_after_reflection(self, state: CompanionState) -> None:
        state.cycle_started_at = time.time()
        state.cycle_message_count = 0
        state.cycle_negative_weight = 0.0
        state.cycle_positive_weight = 0.0
        state.cycle_repair_weight = 0.0
        state.cycle_boundary_hits = 0
        state.cycle_affection_hits = 0
        state.cycle_repair_hits = 0
        state.cycle_dominant_class = "normal"
        state.cycle_instruction_tone = state.next_cycle_tone or "normal"
        state.cycle_instruction = self._instruction_for_dominant("normal")
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
            value = result.get(delta_key)
            if value is not None:
                deltas[state_key] = float(value)
        self._clamp_reflection_energy_delta(deltas)
        self._apply_energy_tier_to_consumption(state, deltas)
        deltas = self._shape_reflection_deltas(state, deltas)
        applied = self._apply_deltas(state, deltas)
        state.today_familiarity_gain += max(0.0, applied.get("familiarity", 0.0))
        state.today_closeness_gain += max(0.0, applied.get("closeness", 0.0))
        mood = result.get("mood")
        if mood:
            state.mood = str(mood)
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
        next_instruction = str(result.get("next_cycle_instruction") or "").strip()
        if next_instruction:
            state.next_cycle_instruction = next_instruction[:180]
        state.last_state_updated_at = time.time()
        state.last_posture = self.explain_posture(state)
        state.clamp()
        return applied

    def _update_cycle_state(self, state: CompanionState, event: InteractionEvent) -> None:
        state.cycle_message_count += 1
        if event.type == "affection":
            state.cycle_affection_hits += 1
        if event.event_class == "repair":
            state.cycle_repair_hits += 1

        if event.event_class == "boundary_violation":
            state.cycle_negative_weight += 3.0
            state.cycle_boundary_hits += 1
        elif event.type == "affection" and state.familiarity < 8.0:
            state.cycle_negative_weight += 2.0
            state.cycle_boundary_hits += 1
        elif event.type == "affection" and (state.boundary_pressure > 25.0 or state.closeness < 0.0):
            state.cycle_negative_weight += 1.5
            state.cycle_boundary_hits += 1
        elif event.event_class == "prosocial":
            state.cycle_positive_weight += 0.8
        elif event.event_class == "repair":
            repair_gain = 0.6 * self._repair_multiplier(state.cycle_negative_weight)
            state.cycle_repair_weight += repair_gain
            state.cycle_negative_weight = max(0.0, state.cycle_negative_weight - repair_gain * 0.4)
        elif event.event_class == "withdrawal":
            if event.type in {"rest_request", "low_energy_share"}:
                state.cycle_positive_weight += 0.2
            else:
                state.cycle_negative_weight += 0.5
        elif event.type == "neutral":
            state.cycle_positive_weight += 0.05

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
        elif state.cycle_repair_weight > 0.0 and state.cycle_boundary_hits > 0:
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
                if value > 0 and key != "boundary_pressure":
                    shaped[key] = value * event.confidence
        self._apply_energy_tier_to_consumption(state, shaped)
        growth_multiplier = 1.0 + min(state.today_messages, 100) / 500.0
        if "familiarity" in shaped and shaped["familiarity"] > 0:
            shaped["familiarity"] *= growth_multiplier * self._saturation_multiplier(state.familiarity)
            shaped["familiarity"] = min(shaped["familiarity"], max(0.0, self.DAILY_FAMILIARITY_CAP - state.today_familiarity_gain))
        if "closeness" in shaped and shaped["closeness"] > 0:
            if state.familiarity < 10 and state.boundary_pressure > 25:
                shaped["closeness"] = min(shaped["closeness"], 0.3)
            shaped["closeness"] *= self._saturation_multiplier(state.closeness)
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
        last = state.last_state_updated_at or now
        gap = now - last
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
            shaped["closeness"] = min(shaped["closeness"] * self._saturation_multiplier(state.closeness), remaining)
        return shaped

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
        if state.closeness <= -35:
            return "强排斥：不要主动靠近，不开玩笑，不暧昧，不追问；只做必要回应。"
        if state.closeness < 0:
            return "疏离收敛：保持礼貌距离，避免亲昵称呼和主动延展。"
        if state.boundary_pressure >= 65:
            return "强收敛：极少追问，不主动延展，优先尊重边界。"
        if state.boundary_pressure >= 40:
            return "谨慎收敛：回复保持短而稳，减少玩笑和主动推进。"
        if state.energy <= 30:
            return "低能量：温和简短，可以结束话题，不要开启新话题。"
        if state.energy <= 42:
            return "微疲：回复保持自然但偏短，少追问，不主动展开新话题。"
        if state.closeness >= 45 and state.boundary_pressure < 15:
            return "放松亲近：可以自然接话，允许轻微主动延伸。"
        return "稳定自然：正常回应，适度接话，不暴露内部状态。"

    def _apply_deltas(self, state: CompanionState, deltas: dict[str, float]) -> dict[str, float]:
        applied: dict[str, float] = {}
        for key, delta in deltas.items():
            if abs(delta) < 0.01:
                continue
            before = float(getattr(state, key))
            setattr(state, key, before + delta)
            state.clamp()
            after = float(getattr(state, key))
            actual = round(after - before, 2)
            if abs(actual) >= 0.01:
                applied[key] = actual
        return applied
