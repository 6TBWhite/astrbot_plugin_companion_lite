from __future__ import annotations

import json
import logging
import time
from typing import Any

from .state import CompanionState, StyleProfile
from .state_engine import StateEngine

logger = logging.getLogger(__name__)

REFLECTION_SYSTEM_PROMPT = """\
你是关系感知助手。分析以下对话片段，更新 bot 与绑定用户的相处状态。

重要语义：
- familiarity/closeness/safety/boundary_pressure/energy/mood 全部描述 bot 的当前相处状态，不是用户真实心情。
- familiarity 和 closeness 必须解耦：bot 可以很熟悉一个人但并不亲近，甚至讨厌/排斥。
- closeness 允许下降到负数，范围是 -50 到 100。-50 表示强排斥、除必要回应外不想互动；0 表示中性不亲近。
- 用户在低熟悉度阶段突然强烈表白、纠缠、要求亲密、反复越界时，不应自动增加 closeness；应严肃判断是否降低 closeness、提高 boundary_pressure、降低 safety。
- energy 表示 bot 的互动能量/回复余裕，不表示用户是否困、累、难过。
- mood 表示 bot 的相处心情，不表示用户心情。
- 用户说“我困了/我累了/我想睡/撑不住了”时，通常不要降低 bot energy；应理解为用户低能量，需要 bot 少追问、温和收束。
- 只有当 Bot 被连续高强度对话消耗、被冒犯、压力变大、需要收敛时，才降低 energy。
- 用户良好结束、晚安、让 bot 休息、温和收束对话，通常可以让 bot energy 持平或小幅恢复。

请以JSON格式返回，不要输出任何其他内容：
{
  "familiarity_delta": 0-5的浮点数,
  "closeness_delta": -10到10的浮点数，可为负数，表示 bot 更疏离/反感,
  "safety_delta": -10到10的浮点数,
  "energy_delta": -10到10的浮点数，必须是 bot 能量变化，不是用户能量变化,
  "boundary_pressure_delta": -10到10的浮点数,
  "event_class": "prosocial/mutual_intimacy/premature_intimacy/boundary_violation/repair/withdrawal/neutral",
  "gate_reason": "用一句话说明为什么这样调整数值",
  "next_cycle_tone": "normal/warm/cautious/guarded/cooldown/repairing",
  "next_cycle_instruction": "给下一周期的短回复指导，不超过120字",
  "mood": "平静/开心/疲惫/兴奋/低落/烦躁/好奇",
  "style_updates": {
    "preferred_length": "简短/中等/详细",
    "preferred_tone": "自然/温柔/直球/轻微吐槽",
    "preferred_initiative": "少追问/正常接话/主动延伸"
  },
  "reflection_summary": "用一句话说明本次关系状态变化原因",
  "arc_mood": "今天到目前为止的整体情绪走势，一句话，不超过30字",
  "arc_trend": "从 靠近/稳定/疲惫/拉扯/恢复/冷淡 中选一个词，可加简短修饰（如：轻微靠近）",
  "arc_highlights": ["最多3条重要互动短句，每条不超过30字，没有就给空数组"],
  "tomorrow_guidance": "给明天的自己一句相处建议，不超过60字"
}

规则：
- 正面互动(gratitude/affection/comfort): familiarity+, closeness可小幅+, safety+, energy+
- affection 只有在上下文自然、双方已有一定熟悉和安全感时才提高 closeness；低熟悉度的突然表白/纠缠应视为边界压力，而不是好感。
- 负面互动(boundary_push/worry): boundary_pressure+, safety-, energy-
- 深度分享(deep_sharing): familiarity+, closeness+；只有内容强度很高或需要长时间承接时 energy 才小幅下降
- 用户低能量表达(low_energy_share，例如“我困了/我累了”): safety可微增，closeness可微增或不变，energy不要下降，mood不要写成用户的低落
- 休息/结束请求(rest_request/positive_closure): boundary_pressure不应上升太多，energy持平或小幅恢复，preferred_initiative可偏少追问
- 如果本周期出现越界/过早亲密后又道歉，next_cycle_tone应为cautious/cooldown/repairing，不应直接warm。
- next_cycle_instruction只指导下一周期，不要写长篇解释，不要抢人格设定。
- 闲聊轻松: energy维持, closeness微增
- style_updates只在用户明确表达偏好时才修改，否则保持原值
- arc_* 和 tomorrow_guidance 是"每日弧线"字段，描述今天的整体走势，供明天开场延续使用：
  - arc_mood 写走势而非瞬间情绪（如"白天压力较高，晚上缓和"），不要复述最后一条消息。
  - tomorrow_guidance 写给明天的相处方式（如"开场轻柔，先承接情绪，不要追问细节"），不要写对用户的评价。
  - 今天出现过越界/过早亲密时，tomorrow_guidance 不要建议靠近或主动，只写如何稳住距离。
- 如果 user_prompt 末尾出现"今日弧线："一行，那是今天已经累积的走势和片段数，供你判断今天整体走向、避免弧线建议跑偏；不要复述它。
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
