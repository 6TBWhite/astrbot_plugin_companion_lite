from __future__ import annotations

import json
import logging
import time
from typing import Any

from ..core.state import CompanionState, StyleProfile
from ..core.state_engine import StateEngine

logger = logging.getLogger(__name__)

REFLECTION_SYSTEM_PROMPT = """\
你是关系感知助手。分析对话片段，更新 bot 与用户的相处状态。

语义要点：
- 所有指标描述 bot 的状态，不是用户心情。energy 是 bot 互动余裕，不是用户困累。
- familiarity 和 closeness 解耦：可以很熟但不亲近甚至排斥。closeness 范围 -50~100。
- 低熟悉度时突然表白/纠缠/越界 → 降 closeness、提 boundary_pressure、降 safety，不加 closeness。
- 用户说"我困了/累了" → 不降 bot energy，理解为用户需要温和收束。
- 只有 bot 被连续消耗/冒犯/施压时才降 energy。休息/晚安/温和收束 → energy 持平或微恢复。

返回JSON，不要其他内容：
{
  "familiarity_delta": "0-5",
  "closeness_delta": "-10到10，负数=更疏离",
  "safety_delta": "-10到10",
  "energy_delta": "-10到10，必须是bot能量变化",
  "boundary_pressure_delta": "-10到10",
  "event_class": "prosocial/mutual_intimacy/premature_intimacy/boundary_violation/repair/withdrawal/neutral",
  "gate_reason": "一句话说明调整原因",
  "next_cycle_tone": "normal/warm/cautious/guarded/cooldown/repairing",
  "next_cycle_instruction": "下周期短回复指导，≤120字",
  "mood": "平静/开心/疲惫/兴奋/低落/烦躁/好奇",
  "style_updates": {"preferred_length":"简短/中等/详细","preferred_tone":"自然/温柔/直球/轻微吐槽","preferred_initiative":"少追问/正常接话/主动延伸"},
  "reflection_summary": "一句话说明变化原因",
  "arc_mood": "今天整体情绪走势，≤30字",
  "arc_trend": "从 靠近/稳定/疲惫/拉扯/恢复/冷淡 中选一个词",
  "arc_highlights": ["最多3条互动短句，每条≤30字，没有给空数组"],
  "tomorrow_guidance": "给明天的相处建议，≤60字"
}

规则：
- 正面互动：familiarity+, closeness小幅+, safety+, energy+（低熟悉度突然亲密除外）
- 负面互动：boundary_pressure+, safety-, energy-
- 深度分享：familiarity+, closeness+；强度高时energy小幅降
- 越界后道歉：next_cycle_tone 用 cautious/cooldown/repairing，不直接warm
- style_updates 只在用户明确表达偏好时改，否则保持原值
- tomorrow_guidance 写相处方式不写评价；今天有越界时不建议靠近，只写如何稳住距离
- user_prompt 末尾"今日弧线："是今天累积走势，供判断用，不要复述
"""


class DeepReflection:
    def __init__(self, llm_request_func: Any, provider_id: str = "") -> None:
        self._llm_request = llm_request_func
        self._provider_id = provider_id
        self._state_engine = StateEngine()

    async def reflect(
        self,
        state: CompanionState,
        style: StyleProfile,
        messages: list[dict[str, Any]],
        arc_brief: str = "",
    ) -> dict[str, Any]:
        if not messages:
            return {}

        dialogue = self._format_messages(messages)
        current_state_desc = (
            f"熟悉度{state.familiarity:.0f}，亲近度{state.closeness:.0f}，"
            f"安全感{state.safety:.0f}，能量{state.energy:.0f}，"
            f"边界压力{state.boundary_pressure:.0f}，心情{state.mood}"
        )
        user_prompt = f"当前状态：{current_state_desc}\n\n近期对话：\n{dialogue}"
        if arc_brief:
            user_prompt += f"\n\n{arc_brief}"

        try:
            response = await self._llm_request(
                prompt=user_prompt,
                system_prompt=REFLECTION_SYSTEM_PROMPT,
                provider_id=self._provider_id or None,
            )
            result = self._parse_response(response)
            result = self._state_engine.sanitize_reflection_result(result)
            logger.debug("[CL] 深度反思结果: %s", json.dumps(result, ensure_ascii=False))
            return result
        except Exception as e:
            logger.warning("[CL] 深度反思失败: %s", e)
            return {}

    def _format_messages(self, messages: list[dict[str, Any]]) -> str:
        parts = []
        for msg in messages:
            role = "用户" if msg.get("role") == "user" else "Bot"
            content = msg.get("content", "")
            ts = msg.get("timestamp", 0)
            time_str = time.strftime("%H:%M", time.localtime(ts)) if ts else ""
            parts.append(f"[{time_str}] {role}: {content}")
        return "\n".join(parts)

    def _parse_response(self, response: str) -> dict[str, Any]:
        try:
            cleaned = response.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[1].split("```")[0].strip()
            elif "```" in cleaned:
                cleaned = cleaned.split("```")[1].split("```")[0].strip()
            return json.loads(cleaned)
        except (json.JSONDecodeError, IndexError):
            logger.warning("[CL] 无法解析反思JSON响应: %s", response[:200])
            return {}

    def apply_result(self, state: CompanionState, style: StyleProfile, result: dict[str, Any]) -> None:
        if not result:
            return

        self._state_engine.apply_reflection_delta(state, result)

        style_updates = result.get("style_updates", {})
        if not isinstance(style_updates, dict):
            return
        length = style_updates.get("preferred_length")
        tone = style_updates.get("preferred_tone")
        initiative = style_updates.get("preferred_initiative")
        if length in ("简短", "中等", "详细"):
            style.preferred_length = length
        if tone in ("自然", "温柔", "直球", "轻微吐槽"):
            style.preferred_tone = tone
        if initiative in ("少追问", "正常接话", "主动延伸"):
            style.preferred_initiative = initiative
        style.updated_at = time.time()
