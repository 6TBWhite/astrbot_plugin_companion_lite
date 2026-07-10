from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from ..core.state import CompanionState
from ..core.storage import Storage

logger = logging.getLogger(__name__)

# arc_trend 规范词。LLM 输出带修饰时（如"轻微靠近"），趋势统计按包含关系归一。
TREND_VOCAB = ("靠近", "稳定", "疲惫", "拉扯", "恢复", "冷淡")

# guidance 消毒：低熟悉度时出现这些词的建议直接丢弃（防"明天更亲近一点"式越级指导）。
INTIMACY_GUIDANCE_KEYWORDS = ("表白", "亲密", "恋人", "更亲近", "撒娇", "亲昵")

# cooldown/cautious 周期下，guidance 含这些词的句子跳过，只保留情绪承接部分。
ADVANCE_KEYWORDS = ("靠近", "主动", "推进", "亲近", "热情", "撒娇")

MOOD_MAX = 60
TREND_MAX = 60
HIGHLIGHT_MAX = 60
HIGHLIGHT_COUNT = 3
GUIDANCE_MAX = 120
SEGMENT_MAX = 60
CONTINUITY_MAX = 150

# 弧线过期规则：昨天的 arc 距今超过 48 小时未更新则不注入（防过时 guidance 答非所问）。
ARC_STALE_SECONDS = 48 * 3600

LLMRequestFunc = Callable[..., Awaitable[str]]

FINALIZE_SYSTEM_PROMPT = """\
你是关系弧线总结助手。请把今天累积的多条相处建议片段压缩成一条给明天的相处指导。

要求：
- 只输出一条不超过60字的建议，不要输出任何其他内容。
- 写给明天的相处方式（如"开场轻柔，先承接情绪，不要追问细节"），不要写对用户的评价。
- 合并重复要点，保留最重要的1-2条意图。
- 如果片段之间冲突，以最后一条为准（最近的反思最贴近当前状态）。
- 如果今天出现过越界/过早亲密，不要建议靠近或主动，只写如何稳住距离。
"""


class ArcEngine:
    """每日情感弧线：由反思结果逐步累积，跨天时压缩成一条 finalized 指导，供次日连续性注入。"""

    def __init__(
        self,
        storage: Storage,
        lookback_days: int = 3,
        llm_request_func: LLMRequestFunc | None = None,
        llm_provider_id: str = "",
        enable_finalization: bool = True,
        midday_compress_threshold: int = 4,
        max_segments: int = 5,
    ) -> None:
        self._storage = storage
        self._lookback_days = max(1, min(7, lookback_days))
        self._llm_request = llm_request_func
        self._llm_provider_id = llm_provider_id
        self._enable_finalization = enable_finalization
        self._midday_compress_threshold = max(0, midday_compress_threshold)
        self._max_segments = max(1, max_segments)

    # ---------- 写入 ----------

    def update_from_reflection(self, user_id: str, result: dict, state: CompanionState) -> None:
        """反思成功后调用。guidance 改为累积到 segments，不再覆盖 tomorrow_guidance。"""
        mood = str(result.get("arc_mood") or "").strip()[:MOOD_MAX]
        trend = str(result.get("arc_trend") or "").strip()[:TREND_MAX]
        raw_guidance = str(result.get("tomorrow_guidance") or "").strip()[:GUIDANCE_MAX]
        highlights = self._clean_highlights(result.get("arc_highlights"))

        if not (mood or trend or raw_guidance or highlights):
            return

        raw_guidance = self._sanitize_guidance(raw_guidance, state)

        today = time.strftime("%Y-%m-%d")
        existing = self._storage.get_daily_arc(user_id, today) or {}
        merged_highlights = self._merge_highlights(existing.get("important_interactions", []), highlights)
        segments = list(existing.get("guidance_segments", []))
        if raw_guidance:
            segments.append(raw_guidance[:SEGMENT_MAX])

        if self._midday_compress_threshold > 0 and len(segments) >= self._midday_compress_threshold:
            segments = self._compress_segments_local(segments)

        segments = segments[-self._max_segments :]

        arc = {
            "overall_mood": mood or existing.get("overall_mood", ""),
            "relationship_trend": trend or existing.get("relationship_trend", ""),
            "important_interactions": merged_highlights,
            "tomorrow_guidance": existing.get("tomorrow_guidance", ""),
            "guidance_segments": segments,
            "finalized": existing.get("finalized", False),
            "cycle_count": int(existing.get("cycle_count", 0)) + 1,
            "source": existing.get("source", "local"),
        }
        self._storage.upsert_daily_arc(user_id, today, arc)
        logger.debug(
            "[CL] 弧线更新 user=%s date=%s trend=%s segments=%d cycle=%d",
            user_id,
            today,
            arc["relationship_trend"],
            len(segments),
            arc["cycle_count"],
        )

    async def finalize_arc_for_date(self, user_id: str, date: str) -> bool:
        """把指定日期的累积 segments 压缩成一条 finalized tomorrow_guidance。

        成功返回 True；无 LLM 或无数据或失败返回 False。
        """
        if not self._enable_finalization:
            return False
        arc = self._storage.get_daily_arc(user_id, date)
        if not arc or arc.get("finalized"):
            return False
        segments = arc.get("guidance_segments", []) or []
        mood = arc.get("overall_mood", "")
        trend = arc.get("relationship_trend", "")
        if not segments and not mood and not trend:
            arc["finalized"] = True
            self._storage.upsert_daily_arc(user_id, date, arc)
            return True

        guidance = ""
        if self._llm_request is not None and segments:
            try:
                guidance = await self._llm_compress_segments(segments, mood, trend)
            except Exception as exc:
                logger.warning("[CL] 弧线 finalize LLM 调用失败 user=%s date=%s: %s", user_id, date, exc)
                guidance = ""
        if not guidance:
            guidance = segments[-1] if segments else ""

        arc["tomorrow_guidance"] = guidance[:GUIDANCE_MAX]
        arc["finalized"] = True
        self._storage.upsert_daily_arc(user_id, date, arc)
        logger.info(
            "[CL] 弧线 finalize user=%s date=%s segments=%d guidance=%s",
            user_id,
            date,
            len(segments),
            arc["tomorrow_guidance"][:40],
        )
        return True

    async def _llm_compress_segments(self, segments: list[str], mood: str, trend: str) -> str:
        if self._llm_request is None:
            return ""
        seg_text = "\n".join(f"- {s}" for s in segments)
        user_prompt = f"今天整体走势：{mood or '未知'}，趋势：{trend or '未知'}。\n累积建议片段：\n{seg_text}"
        resp = await self._llm_request(
            prompt=user_prompt,
            system_prompt=FINALIZE_SYSTEM_PROMPT,
            provider_id=self._llm_provider_id or "",
        )
        text = (resp or "").strip()
        if "```" in text:
            text = text.split("```")[0].strip() or text
        return text[:SEGMENT_MAX]

    @staticmethod
    def _compress_segments_local(segments: list[str]) -> list[str]:
        """日中压缩：无 LLM 时的本地兜底，保留首尾两条 + 中间去重。"""
        if len(segments) <= 1:
            return segments
        head = segments[0]
        tail = segments[-1]
        return [head, tail]

    @staticmethod
    def _clean_highlights(raw: object) -> list[str]:
        if not isinstance(raw, list):
            return []
        cleaned = []
        for item in raw[:HIGHLIGHT_COUNT]:
            text = str(item).strip()[:HIGHLIGHT_MAX]
            if text:
                cleaned.append(text)
        return cleaned

    @staticmethod
    def _merge_highlights(old: list, new: list[str]) -> list[str]:
        """合并去重，保留最新的 3 条（新条目优先）。"""
        merged: list[str] = []
        old_list = [str(x) for x in old if isinstance(old, list)]
        for item in list(new) + old_list:
            if item and item not in merged:
                merged.append(item)
        return merged[:HIGHLIGHT_COUNT]

    @staticmethod
    def _sanitize_guidance(guidance: str, state: CompanionState) -> str:
        if not guidance:
            return ""
        if state.familiarity < 8.0 and any(kw in guidance for kw in INTIMACY_GUIDANCE_KEYWORDS):
            logger.debug("[CL] guidance 消毒：低熟悉度亲密建议被丢弃: %s", guidance)
            return ""
        return guidance

    # ---------- 读取 / 注入 ----------

    def build_continuity_text(self, user_id: str, today: str = "", cycle_dominant: str = "normal") -> str:
        """读取昨天的 finalized arc + 近 N 天 trend 序列，现算连续性提示。无昨日弧线返回空。"""
        today = today or time.strftime("%Y-%m-%d")
        arcs = self._storage.get_recent_arcs(user_id, days=self._lookback_days, before_date=today)
        if not arcs:
            return ""
        yesterday_arc = arcs[0]
        # 过期检查：最近一条弧线超过 48 小时未更新则整块不注入。
        if time.time() - float(yesterday_arc.get("updated_at") or 0) > ARC_STALE_SECONDS:
            return ""

        parts: list[str] = []
        mood = yesterday_arc.get("overall_mood", "")
        guidance = yesterday_arc.get("tomorrow_guidance", "")
        # 只注入 finalized 的 guidance；未 finalize 的降级只用 mood+trend，避免答非所问。
        if not yesterday_arc.get("finalized"):
            guidance = ""
        if cycle_dominant in ("cooldown", "cautious"):
            guidance = self._strip_advance_sentences(guidance)
        if mood and guidance:
            parts.append(f"上次相处整体{mood}。{guidance}")
        elif mood:
            parts.append(f"上次相处整体{mood}。")
        elif guidance:
            parts.append(guidance)

        trend_text = self._trend_text([a.get("relationship_trend", "") for a in reversed(arcs)])
        if trend_text:
            parts.append(trend_text)

        text = "".join(parts).strip()
        return text[:CONTINUITY_MAX]

    def build_today_arc_brief(self, user_id: str) -> str:
        """给反思 LLM 看的今日弧线背景摘要（定长，~80字）。未 finalize 也注入，让反思知道今天走向。"""
        today = time.strftime("%Y-%m-%d")
        arc = self._storage.get_daily_arc(user_id, today)
        if not arc:
            return ""
        mood = arc.get("overall_mood", "")
        trend = arc.get("relationship_trend", "")
        seg_count = len(arc.get("guidance_segments", []))
        parts = []
        if mood:
            parts.append(f"走势:{mood}")
        if trend:
            parts.append(f"趋势:{trend}")
        if seg_count:
            parts.append(f"已累积{seg_count}条建议片段")
        if not parts:
            return ""
        return "今日弧线：" + "，".join(parts) + "。"

    @staticmethod
    def _strip_advance_sentences(guidance: str) -> str:
        """cooldown/cautious 周期下移除含'靠近/主动/推进'类词的句子，保留情绪承接部分。"""
        if not guidance:
            return ""
        sentences = [s for s in guidance.replace("；", "。").split("。") if s.strip()]
        kept = [s for s in sentences if not any(kw in s for kw in ADVANCE_KEYWORDS)]
        return "。".join(kept) + "。" if kept else ""

    def _trend_text(self, trends: list[str]) -> str:
        trends = [t for t in trends if t]
        if not trends:
            return ""
        normalized = [self._normalize_trend(t) for t in trends]
        if len(set(trends)) == 1:
            text = f"近几天持续{trends[0]}。"
        elif len(trends) >= 2 and trends[-1] != trends[-2]:
            text = f"近几天从{trends[-2]}转向{trends[-1]}。"
        else:
            text = f"近几天趋势：{' -> '.join(trends)}。"
        if normalized.count("疲惫") >= 2:
            text += "注意近几天能量偏低，整体收着点。"
        if normalized.count("拉扯") >= 2:
            text += "最近反复拉扯，避免主动推进关系。"
        return text

    @staticmethod
    def _normalize_trend(trend: str) -> str:
        for vocab in TREND_VOCAB:
            if vocab in trend:
                return vocab
        return trend

    # ---------- 面板 ----------

    def get_today_arc(self, user_id: str) -> dict | None:
        return self._storage.get_daily_arc(user_id, time.strftime("%Y-%m-%d"))

    def get_recent_arcs(self, user_id: str, days: int = 7) -> list[dict]:
        return self._storage.get_recent_arcs(user_id, days=days)
