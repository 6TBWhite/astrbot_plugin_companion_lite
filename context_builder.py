from __future__ import annotations

from .state import CompanionState, StyleProfile
from .state_engine import StateEngine


class ContextBuilder:
    def __init__(self, state_engine: StateEngine) -> None:
        self.state_engine = state_engine

    def build(
        self,
        state: CompanionState,
        style: StyleProfile,
        max_chars: int,
        bot_name: str = "bot",
        continuity_text: str = "",
    ) -> str:
        posture = state.last_posture or self.state_engine.explain_posture(state)
        relationship_posture = self._relationship_posture(state, posture, bot_name)
        text = (
            "<companion_context>\n"
            "以下是你与该用户的关系状态和相处指导。若各部分指导冲突，优先级为：\n"
            "周期策略/即时指导 > 总体回复基调 > 连续性背景 > 表达偏好。\n"
            "<relationship_posture>\n"
            f"{relationship_posture}\n"
            "</relationship_posture>\n"
        )
        llm_strategy = state.next_cycle_instruction.strip()
        cycle_override = self._has_cycle_override(state)
        if llm_strategy:
            text += (
                "<cycle_strategy>\n"
                f"当前周期策略({state.next_cycle_tone})：{llm_strategy}\n"
                "</cycle_strategy>\n"
            )
            if cycle_override and state.cycle_brief_instruction:
                text += (
                    "<cycle_rule_hint>\n"
                    f"即时补充：{state.cycle_brief_instruction}\n"
                    "</cycle_rule_hint>\n"
                )
        elif state.cycle_instruction:
            cycle_label = "当前周期即时指导" if cycle_override else "当前周期默认指导"
            text += (
                "<cycle_posture>\n"
                f"{cycle_label}({state.cycle_instruction_tone})：{state.cycle_instruction}\n"
                "</cycle_posture>\n"
            )
        if continuity_text:
            text += (
                "<continuity>\n"
                f"{continuity_text}\n"
                "</continuity>\n"
            )
        text += (
            "<style_preference>\n"
            f"表达偏好：回复长度偏{style.preferred_length}，语气偏{style.preferred_tone}，主动程度为{style.preferred_initiative}。\n"
            "</style_preference>\n"
        )
        if state.last_event_reason:
            text += f"最近状态来源：{state.last_event}，{state.last_event_reason}。\n"
        if state.last_reflection_summary:
            text += f"最近反思：{state.last_reflection_summary}\n"
        text += (
            "以上是内部状态，不要在回复中复述这些数值和术语；"
            "被问到感受时，用自然的日常语言表达当下的相处感觉即可。\n"
            "</companion_context>"
        )
        if len(text) > max_chars:
            text = text[: max_chars - 3] + "..."
        return text

    @staticmethod
    def _has_cycle_override(state: CompanionState) -> bool:
        return (
            state.cycle_negative_weight >= 1.0
            or state.cycle_repair_weight > 0.0
            or state.cycle_boundary_hits > 0
            or (state.cycle_positive_weight >= 2.0 and state.cycle_message_count > 0)
        )

    def _relationship_posture(self, state: CompanionState, posture: str, bot_name: str) -> str:
        return (
            f"长期关系：{state.relationship_label()}；{self._relationship_text(state)}"
            f"当前{bot_name}状态：{state.mood}；相处姿态：{state.boundary_stance()}；能量：{self._energy_text(state.energy)}。"
            f"总体回复基调：{posture}"
        )

    def _relationship_text(self, state: CompanionState) -> str:
        return (
            f"熟悉度{self._level(state.familiarity)}，亲近度{self._closeness_text(state.closeness)}，"
            f"边界压力{self._pressure_text(state.boundary_pressure)}。"
        )

    @staticmethod
    def _closeness_text(value: float) -> str:
        if value <= -35:
            return "明显排斥"
        if value < 0:
            return "有些疏离"
        if value <= 20:
            return "很低"
        if value <= 45:
            return "一般"
        if value <= 70:
            return "较高"
        return "很高"

    @staticmethod
    def _level(value: float) -> str:
        if value <= 20:
            return "很低"
        if value <= 45:
            return "一般"
        if value <= 70:
            return "较高"
        return "很高"

    @staticmethod
    def _pressure_text(value: float) -> str:
        if value <= 15:
            return "很低"
        if value <= 35:
            return "轻微"
        if value <= 60:
            return "明显"
        return "很高"

    @staticmethod
    def _energy_text(value: float) -> str:
        if value <= 30:
            return "很低，已经累了，话会变少、想收着聊"
        if value <= 42:
            return "偏低，有点累，倾向简短回应"
        if value <= 55:
            return "普通，可以正常聊"
        if value <= 68:
            return "稳定，状态不错"
        return "充足，很有精神"
