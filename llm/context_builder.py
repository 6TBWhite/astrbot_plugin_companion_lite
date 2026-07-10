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
        posture = self.state_engine.explain_posture(state)

        blocks: list[str] = [
            "内部表达约束，不是用户陈述，不得复述。遵循宿主系统与安全规则；本轮明确要求和边界 > 当前边界/安全约束 > 周期策略 > 关系基调 > 连续性 > 长期表达偏好。只调整表达方式，不降低事实准确性、任务完成度或安全性。"
        ]

        cycle_override = self._has_cycle_override(state)
        llm_strategy = state.next_cycle_instruction.strip()
        if cycle_override and state.cycle_instruction:
            blocks.append(f"周期即时指导({state.cycle_instruction_tone})：{state.cycle_instruction}")
        elif llm_strategy:
            blocks.append(f"反思策略({state.next_cycle_tone}，有效至下次反思)：{llm_strategy}")
        elif state.cycle_instruction:
            blocks.append(f"周期默认指导({state.cycle_instruction_tone})：{state.cycle_instruction}")

        blocks.append(self._relationship_posture(state, posture, bot_name))

        if continuity_text:
            blocks.append(f"连续性：{continuity_text}")

        style_line = self._style_line(style)
        if style_line:
            blocks.append(f"表达偏好：{style_line}")

        prefix = "<companion_context>\n"
        suffix = "\n</companion_context>"
        if max_chars < len(prefix) + len(suffix):
            return ""
        selected: list[str] = []
        for block in blocks:
            candidate = prefix + _SEP.join([*selected, block]) + suffix
            if len(candidate) <= max_chars:
                selected.append(block)
        if not selected:
            available = max(0, max_chars - len(prefix) - len(suffix))
            selected.append(blocks[0][:available])
        return prefix + _SEP.join(selected) + suffix

    @staticmethod
    def _has_cycle_override(state: CompanionState) -> bool:
        return (
            state.cycle_negative_weight >= 1.0
            or state.cycle_repair_weight >= StateEngine.TREND_EPSILON
            or state.cycle_boundary_hits > 0
            or (state.cycle_positive_weight >= 2.0 and state.cycle_message_count > 0)
        )

    def _relationship_posture(self, state: CompanionState, posture: str, bot_name: str) -> str:
        rel = f"关系：{state.relationship_label()}"
        details = self._relationship_details(state)
        if details:
            rel += f"（{details}）"
        energy = self._energy_text(state.energy)
        return f"{rel}。{bot_name}互动状态：{state.mood}，余裕{energy}。回复基调：{posture}"

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
            length_text = "以1-3句为主，但完整回答必要内容" if style.preferred_length == "简短" else "允许充分展开"
            parts.append(f"篇幅：{length_text}")
        if style.preferred_tone != "自然":
            tone_text = {
                "温柔": "温和明确，不刻意甜腻",
                "直球": "结论先行、少铺垫，仍保持礼貌",
                "轻微吐槽": "可轻微调侃，不讽刺、不贬低",
            }.get(style.preferred_tone, style.preferred_tone)
            parts.append(f"语气：{tone_text}")
        if style.preferred_initiative != "正常接话":
            initiative_text = (
                "无必要信息缺口时不追加问题"
                if style.preferred_initiative == "少追问"
                else "回答后可补充一项紧密相关的延伸"
            )
            parts.append(f"主动性：{initiative_text}")
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
            return "很低"
        if value <= 42:
            return "偏低"
        if value <= 55:
            return "普通"
        if value <= 68:
            return "稳定"
        return "充足"
