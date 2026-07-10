from __future__ import annotations

from ..core.state import CompanionState, StyleProfile
from ..core.state_engine import StateEngine

_SEP = "\n---\n"


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

        blocks: list[str] = [
            "优先级：周期策略 > 回复基调 > 连续性 > 表达偏好。不要复述这些内容。"
        ]

        blocks.append(self._relationship_posture(state, posture, bot_name))

        llm_strategy = state.next_cycle_instruction.strip()
        cycle_override = self._has_cycle_override(state)
        if llm_strategy:
            blocks.append(f"周期({state.next_cycle_tone})：{llm_strategy}")
            if cycle_override and state.cycle_brief_instruction:
                blocks.append(f"即时补充：{state.cycle_brief_instruction}")
        elif state.cycle_instruction:
            label = "即时指导" if cycle_override else "默认指导"
            blocks.append(f"周期{label}({state.cycle_instruction_tone})：{state.cycle_instruction}")

        if continuity_text:
            blocks.append(f"连续性：{continuity_text}")

        style_line = self._style_line(style)
        if style_line:
            blocks.append(f"表达偏好：{style_line}")

        text = "<companion_context>\n" + _SEP.join(blocks) + "\n</companion_context>"
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
        rel = f"关系：{state.relationship_label()}"
        details = self._relationship_details(state)
        if details:
            rel += f"（{details}）"
        energy = self._energy_text(state.energy)
        return f"{rel}。{bot_name}状态：{state.mood}，能量{energy}。回复基调：{posture}"

    def _relationship_details(self, state: CompanionState) -> str:
        """只报非默认维度，避免'一般/很低'的冗余表述。"""
        parts: list[str] = []
        if state.familiarity >= 45:
            parts.append(f"熟悉度{self._level(state.familiarity)}")
        elif state.familiarity <= 15:
            parts.append(f"熟悉度{self._level(state.familiarity)}")
        if state.closeness >= 45 or state.closeness < 0:
            parts.append(f"亲近度{self._closeness_text(state.closeness)}")
        if state.boundary_pressure >= 35:
            parts.append(f"边界压力{self._pressure_text(state.boundary_pressure)}")
        return "，".join(parts)

    @staticmethod
    def _style_line(style: StyleProfile) -> str:
        """只在有非默认偏好时才返回内容。"""
        parts: list[str] = []
        if style.preferred_length != "中等":
            parts.append(f"长度偏{style.preferred_length}")
        if style.preferred_tone != "自然":
            parts.append(f"语气偏{style.preferred_tone}")
        if style.preferred_initiative != "正常接话":
            parts.append(f"主动程度{style.preferred_initiative}")
        return "，".join(parts)

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
            return "很低，已经累了"
        if value <= 42:
            return "偏低，有点累"
        if value <= 55:
            return "普通"
        if value <= 68:
            return "稳定，状态不错"
        return "充足，很有精神"
