from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.event.filter import PermissionType
from astrbot.api.platform import MessageType
from astrbot.api.star import Context, Star, register

try:
    from astrbot.api.web import json_response, request
except ImportError:
    def json_response(payload: dict[str, Any]) -> dict[str, Any]:
        return payload

    request = None

try:
    from astrbot.core.agent.message import TextPart
except ImportError:
    TextPart = None

try:
    from astrbot.core.utils.astrbot_path import get_astrbot_data_path
except ImportError:
    from pathlib import Path as _Path

    def _fallback_data_path() -> str:
        return str(_Path(".").resolve())

    get_astrbot_data_path = _fallback_data_path

from .arc import ArcEngine
from .binding import BindingManager
from .config import CLConfig, load_config
from .context_builder import ContextBuilder
from .events import EventEngine
from .livingmemory_integration import LivingMemoryIntegration
from .reflection import DeepReflection
from .silence import SilenceMechanism
from .state import CompanionState, StyleProfile
from .state_engine import StateEngine
from .storage import Storage

__version__ = "1.0.0"

SYSTEM_COMMAND_RE = re.compile(r"(?:^|\s)/[A-Za-z0-9_\-\u4e00-\u9fff]+(?:\s|$)")
PROCESSED_USER_MESSAGE_EXTRA = "_companion_lite_processed_user_message"


@register(
    "astrbot_plugin_companion_lite",
    "companion-lite",
    "私人陪伴场景关系感知插件。跟踪熟悉度、亲近度、安全感等关系状态，注入个性化上下文到LLM，支持沉默机制。",
    __version__,
)
class CompanionLitePlugin(Star):
    def __init__(self, context: Context, config: dict[str, Any] | None = None) -> None:
        super().__init__(context)
        self.context = context
        self.raw_config = config or {}
        self.plugin_config: CLConfig = load_config(self.raw_config)
        self.binding = BindingManager(self.plugin_config.basic.main_user_ids)
        plugin_data_dir = Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_companion_lite"
        plugin_data_dir.mkdir(parents=True, exist_ok=True)
        db_path = str(plugin_data_dir / "companion_lite.db")
        self.storage = Storage(db_path)
        self.state_engine = StateEngine()
        self.context_builder = ContextBuilder(self.state_engine)
        self.arc_engine = ArcEngine(
            self.storage,
            lookback_days=self.plugin_config.continuity.continuity_lookback_days,
            llm_request_func=self._llm_generate,
            llm_provider_id=self.plugin_config.llm.reflection_provider_id or "",
            enable_finalization=self.plugin_config.continuity.enable_arc_finalization,
            midday_compress_threshold=self.plugin_config.continuity.arc_midday_compress_threshold,
            max_segments=self.plugin_config.continuity.arc_max_segments,
        )
        self.livingmemory = LivingMemoryIntegration(
            context=context,
            enabled=self.plugin_config.livingmemory.delegate_memory_to_livingmemory,
            plugin_name=self.plugin_config.livingmemory.livingmemory_plugin_name,
        )
        self.silence = SilenceMechanism(
            energy_threshold=self.plugin_config.silence.energy_threshold,
            boundary_threshold=self.plugin_config.silence.boundary_threshold,
        )
        self.reflection = DeepReflection(
            llm_request_func=self._llm_generate,
            provider_id=self.plugin_config.llm.reflection_provider_id or "",
        )
        self._initialized = False
        self._init_error: str | None = None
        self._background_tasks: set[asyncio.Task] = set()
        self._reflection_tasks_by_user: dict[str, asyncio.Task] = {}
        self._last_reflection_ts: float = 0.0
        self._last_injected_context_by_user: dict[str, dict[str, Any]] = {}

        self._register_page_api()

    def _register_page_api(self) -> None:
        if not hasattr(self.context, "register_web_api"):
            return
        prefixes = ("/astrbot_plugin_companion_lite/page", "/CompanionLite/page")
        for prefix in prefixes:
            self.context.register_web_api(f"{prefix}/state", self._api_state, ["GET"], "Get companion state")
            self.context.register_web_api(f"{prefix}/style", self._api_style, ["GET"], "Get style profile")
            self.context.register_web_api(f"{prefix}/messages", self._api_messages, ["GET"], "Get message buffer")
            self.context.register_web_api(f"{prefix}/health", self._api_health, ["GET"], "Get plugin health")
            self.context.register_web_api(f"{prefix}/reset", self._api_reset, ["GET"], "Reset companion state")
            self.context.register_web_api(
                f"{prefix}/clear_messages", self._api_clear_messages, ["GET"], "Clear message buffer"
            )
            self.context.register_web_api(
                f"{prefix}/trigger_reflection", self._api_trigger_reflection, ["GET"], "Trigger deep reflection"
            )
            self.context.register_web_api(f"{prefix}/arc", self._api_arc, ["GET"], "Get daily arcs")
            self.context.register_web_api(f"{prefix}/clear_arcs", self._api_clear_arcs, ["GET"], "Clear daily arcs")
        logger.warning("[CL] Debug Web API 已注册: %s", ", ".join(prefixes))

    async def initialize(self) -> None:
        try:
            logger.info(
                "[CL] 插件初始化: "
                f"capture={self.plugin_config.basic.enable_message_capture}, "
                f"hook={self.plugin_config.basic.enable_llm_hook}, "
                f"silence={self.plugin_config.basic.enable_silence}, "
                f"reflection={self.plugin_config.basic.enable_deep_reflection}, "
                f"bound_users={len(self.binding.user_ids)}"
            )
            if not self.binding.configured:
                logger.warning("[CL] 未配置 main_user_ids，插件将不捕获、不注入、不学习")
            lm_active = self.livingmemory.detect()
            logger.info(
                "[CL] LivingMemory 状态: active=%s, plugin=%s",
                lm_active,
                self.livingmemory.instance.display_name if self.livingmemory.instance else "none",
            )
            self._initialized = True
            self._init_error = None
            logger.info("[CL] 初始化完成")
        except Exception as exc:
            self._initialized = False
            self._init_error = str(exc)
            logger.error("[CL] 初始化异常: %s", exc, exc_info=True)

    async def terminate(self) -> None:
        for task in list(self._background_tasks):
            task.cancel()
        self._reflection_tasks_by_user.clear()
        self.storage.close()
        logger.info("[CL] 已停止")

    async def _llm_generate(self, prompt: str, system_prompt: str = "", provider_id: str = "") -> str:
        try:
            provider = self.context.get_provider_by_id(provider_id) if provider_id else None
            if provider is None:
                provider = self.context.get_using_provider(None)
            if provider is None:
                return ""
            resp = await provider.text_chat(
                prompt=prompt,
                system_prompt=system_prompt or "",
                contexts=[],
            )
            return resp.completion_text or ""
        except Exception as e:
            logger.warning("[CL] LLM调用失败: %s", e)
            return ""

    def _main_user_ids(self) -> tuple[str, ...]:
        return self.binding.user_ids

    def _is_main_user(self, user_id: str) -> bool:
        return self.binding.is_bound(user_id)

    def _should_process_text(self, text: str) -> bool:
        if not text:
            return False
        if self._is_system_command_text(text):
            return False
        length = len(text)
        min_len = self.plugin_config.basic.min_message_length
        max_len = self.plugin_config.basic.max_message_length
        return min_len <= length <= max_len

    @staticmethod
    def _is_system_command_text(text: str) -> bool:
        stripped = (text or "").strip()
        if not stripped:
            return False
        if stripped.startswith(("!", "#")):
            return True
        return bool(SYSTEM_COMMAND_RE.search(stripped))

    async def _load_state(self, user_id: str) -> CompanionState:
        record = self.storage.get_state(user_id)
        if record:
            return CompanionState.from_dict(record)
        return CompanionState(user_id=user_id)

    async def _load_state_with_decay(self, user_id: str, save: bool = False) -> CompanionState:
        state = await self._load_state(user_id)
        changed = self.state_engine.apply_time_decay(state)
        if save and changed:
            self._save_state(user_id, state)
        return state

    async def _load_style(self, user_id: str) -> StyleProfile:
        record = self.storage.get_style_profile(user_id)
        if record:
            return StyleProfile.from_dict(record)
        return StyleProfile(user_id=user_id)

    def _save_state(self, user_id: str, state: CompanionState) -> None:
        self.storage.save_state(user_id, state.to_dict())

    def _save_style(self, user_id: str, style: StyleProfile) -> None:
        self.storage.save_style_profile(user_id, style.to_dict())

    def _max_buffer_messages(self) -> int:
        return self.plugin_config.basic.max_buffer_messages

    def _reflection_ready_messages(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        messages = self.storage.get_recent_messages(user_id, limit=limit)
        return [m for m in messages if not self._is_system_command_text(str(m.get("content") or ""))]

    async def _maybe_trigger_reflection(self, user_id: str, state: CompanionState, style: StyleProfile) -> None:
        if not self.plugin_config.basic.enable_deep_reflection:
            return
        msg_count = self.storage.count_messages(user_id)
        interval = self.plugin_config.reflection.reflection_message_interval
        time_interval = self.plugin_config.reflection.reflection_time_interval_minutes * 60
        now = time.time()
        if msg_count < interval:
            return
        if now - state.last_deep_reflection_at < time_interval:
            return
        state.last_deep_reflection_at = now
        self._save_state(user_id, state)
        messages = self._reflection_ready_messages(user_id, limit=20)
        if not messages:
            return
        self._queue_reflection(user_id, state, style, messages)

    async def _capture_user_interaction(
        self, user_id: str, text: str
    ) -> tuple[CompanionState, StyleProfile] | None:
        if not self.plugin_config.basic.enable_message_capture:
            return None
        if not self._should_process_text(text):
            return None

        recent_count = self.storage.count_recent_user_messages(
            user_id,
            self.plugin_config.basic.recent_rate_window_seconds,
        )
        rate = float(recent_count + 1)
        interaction_event = EventEngine.classify(text, rate)
        event_type = interaction_event.type

        state = await self._load_state_with_decay(user_id, save=False)
        style = await self._load_style(user_id)
        update = self.state_engine.apply_event(state, interaction_event)
        EventEngine.apply_style_update(style, event_type)

        self._save_state(user_id, state)
        self._save_style(user_id, style)
        self.storage.append_message(user_id, "user", text, max_messages=self._max_buffer_messages())

        logger.debug(
            "[CL] LLM链路消息捕获: user=%s, event=%s, state=%s/%s/%s, energy=%.1f",
            user_id,
            event_type,
            state.familiarity,
            state.closeness,
            state.safety,
            state.energy,
        )
        if update.deltas:
            logger.debug("[CL] 状态变化: user=%s, reason=%s, deltas=%s", user_id, update.reason, update.deltas)

        await self._maybe_trigger_reflection(user_id, state, style)
        return state, style

    def _queue_reflection(
        self,
        user_id: str,
        state: CompanionState,
        style: StyleProfile,
        messages: list[dict],
    ) -> bool:
        existing = self._reflection_tasks_by_user.get(user_id)
        if existing is not None and not existing.done():
            logger.debug("[CL] 反思任务已在运行，跳过重复触发 user=%s", user_id)
            return False
        task = asyncio.create_task(self._run_reflection(user_id, state, style, messages))
        self._background_tasks.add(task)
        self._reflection_tasks_by_user[user_id] = task
        task.add_done_callback(lambda done_task: self._on_reflection_done(user_id, done_task))
        return True

    def _on_reflection_done(self, user_id: str, task: asyncio.Task) -> None:
        self._background_tasks.discard(task)
        if self._reflection_tasks_by_user.get(user_id) is task:
            self._reflection_tasks_by_user.pop(user_id, None)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.warning("[CL] 反思任务异常 user=%s: %s", user_id, exc, exc_info=exc)

    async def _maybe_finalize_yesterday_arc(self, user_id: str) -> None:
        """跨天补生成：检测昨天（或更早）有没有未 finalize 的弧线，有就压缩收尾。"""
        if not self.plugin_config.continuity.enable_arc_finalization:
            return
        today = time.strftime("%Y-%m-%d")
        try:
            stale = self.storage.get_unfinalized_arc_before(user_id, today)
            if not stale:
                return
            stale_date = stale.get("date", "")
            if not stale_date:
                return
            logger.info("[CL] 检测到未收尾弧线 user=%s date=%s，开始补生成", user_id, stale_date)
            await self.arc_engine.finalize_arc_for_date(user_id, stale_date)
        except Exception as exc:
            logger.warning("[CL] 昨日弧线补生成失败 user=%s: %s", user_id, exc)

    async def _run_reflection(self, user_id: str, state: CompanionState, style: StyleProfile, messages: list[dict]) -> None:
        logger.info("[CL] 开始深度反思 user=%s, messages=%d", user_id, len(messages))
        # 跨天补生成：新一天首次反思时，先把昨天未 finalize 的弧线收尾。
        await self._maybe_finalize_yesterday_arc(user_id)
        result = await self.reflection.reflect(state, style, messages, arc_brief=self.arc_engine.build_today_arc_brief(user_id))
        if result:
            self.reflection.apply_result(state, style, result)
            try:
                self.arc_engine.update_from_reflection(user_id, result, state)
            except Exception as exc:
                logger.warning("[CL] 弧线更新失败（不影响状态更新）user=%s: %s", user_id, exc)
            self.state_engine.reset_cycle_after_reflection(state)
            self._save_state(user_id, state)
            self._save_style(user_id, style)
            logger.info(
                "[CL] 深度反思完成 user=%s: familiarity=%.1f, closeness=%.1f, mood=%s",
                user_id,
                state.familiarity,
                state.closeness,
                state.mood,
            )
            self.storage.clear_messages(user_id)
        else:
            self.storage.trim_messages(user_id, self._max_buffer_messages())
            logger.warning("[CL] 深度反思无有效结果，保留消息缓冲 user=%s", user_id)
        self._last_reflection_ts = time.time()

    def _build_context_text(
        self, state: CompanionState, style: StyleProfile, max_chars: int, bot_name: str = "bot", user_id: str = ""
    ) -> str:
        continuity_text = ""
        if user_id and self.plugin_config.continuity.enable_continuity_injection:
            try:
                continuity_text = self.arc_engine.build_continuity_text(
                    user_id, cycle_dominant=state.cycle_dominant_class
                )
            except Exception as exc:
                logger.warning("[CL] 连续性文本生成失败，跳过注入 user=%s: %s", user_id, exc)
        return self.context_builder.build(
            state, style, max_chars, bot_name=bot_name, continuity_text=continuity_text
        )

    async def _resolve_bot_name(self, event: AstrMessageEvent | None = None) -> str:
        context = self.context
        try:
            persona_manager = getattr(context, "persona_manager", None)
            if persona_manager is not None and hasattr(persona_manager, "get_default_persona_v3"):
                persona = await persona_manager.get_default_persona_v3()
                if isinstance(persona, dict):
                    name = str(persona.get("name") or "").strip()
                    if name:
                        return name
        except Exception:
            pass
        try:
            bot_name = getattr(context, "bot_name", None)
            if bot_name:
                return str(bot_name)
        except Exception:
            pass
        return "bot"

    @staticmethod
    def _describe_level(value: float, low: str, mid_low: str, mid_high: str, high: str) -> str:
        if value <= 20:
            return low
        if value <= 45:
            return mid_low
        if value <= 70:
            return mid_high
        return high

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def capture_private_message(self, event: AstrMessageEvent) -> None:
        # Do not store from the raw message event: AstrBot commands such as /reset can
        # be normalized to plain text here. Real dialogue is captured in on_llm_request.
        return

    @filter.on_llm_request()
    async def inject_companion_context(self, event: AstrMessageEvent, req=None) -> None:
        if not self._initialized or not self.plugin_config.basic.enable_llm_hook:
            return
        if req is None:
            return
        user_id = event.get_sender_id()
        if not self._is_main_user(user_id):
            return

        text = (event.get_message_str() or "").strip()
        already_processed = False
        if hasattr(event, "get_extra"):
            already_processed = bool(event.get_extra(PROCESSED_USER_MESSAGE_EXTRA, False))
        if text and not already_processed:
            captured = await self._capture_user_interaction(user_id, text)
            if captured is not None and hasattr(event, "set_extra"):
                event.set_extra(PROCESSED_USER_MESSAGE_EXTRA, True)

        state = await self._load_state_with_decay(user_id, save=True)
        style = await self._load_style(user_id)

        silence_block = ""
        if self.plugin_config.basic.enable_silence:
            should_silence, silence_text = self.silence.should_inject_silence(state)
            if should_silence:
                silence_block = silence_text[: self.plugin_config.llm.max_context_chars]
                logger.debug("[CL] 注入沉默意图 user=%s, mode=%s", user_id, self.silence.check(state))

        bot_name = await self._resolve_bot_name(event)
        context_text = self._build_context_text(
            state, style, self.plugin_config.llm.max_context_chars, bot_name, user_id=user_id
        )
        combined = f"{context_text}\n{silence_block}" if silence_block else context_text
        self._last_injected_context_by_user[user_id] = {
            "timestamp": time.time(),
            "text": combined,
            "chars": len(combined),
            "cycle_tone": state.cycle_instruction_tone,
            "next_cycle_tone": state.next_cycle_tone,
            "cycle_started_at": state.cycle_started_at,
            "cycle_message_count": state.cycle_message_count,
            "silence_injected": bool(silence_block),
            "continuity_injected": "<continuity>" in combined,
        }

        logger.debug(
            "[CL] 注入上下文: user=%s, rel=%s, mood=%s, energy=%.1f, silence=%s, chars=%d",
            user_id,
            state.relationship_label(),
            state.mood,
            state.energy,
            bool(silence_block),
            len(combined),
        )
        if not self._append_extra_user_content(req, combined):
            prompt = getattr(req, "prompt", "") or ""
            req.prompt = f"{prompt}\n\n{combined}"

    @filter.on_llm_response()
    async def capture_llm_response(self, event: AstrMessageEvent, resp=None) -> None:
        if not self._initialized or not self.plugin_config.basic.enable_message_capture:
            return
        if event.get_message_type() == MessageType.GROUP_MESSAGE:
            return
        user_id = event.get_sender_id()
        if not self._is_main_user(user_id):
            return

        if resp is None:
            return

        if getattr(resp, "role", "assistant") != "assistant":
            return
        if getattr(resp, "tools_call_name", None) or getattr(resp, "tools_call_extra_content", None):
            return

        text = (getattr(resp, "completion_text", "") or "").strip()
        if text:
            self.storage.append_message(user_id, "assistant", text, max_messages=self._max_buffer_messages())

    @filter.command("cp_status")
    @filter.permission_type(PermissionType.ADMIN)
    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def cmd_status(self, event: AstrMessageEvent):
        user_id = event.get_sender_id()
        state = await self._load_state_with_decay(user_id, save=True)
        style = await self._load_style(user_id)
        lines = [
            f"关系状态 ({user_id}):",
            f"  关系阶段: {state.relationship_label()}",
            f"  陪伴模式: {'开启' if state.bonded else '关闭'}",
            f"  熟悉度: {state.familiarity:.1f}  亲近度: {state.closeness:.1f}",
            f"  边界压力: {state.boundary_pressure:.1f}  能量: {state.energy:.1f}",
            f"  边界姿态: {state.boundary_stance()}",
            f"  当前回复姿态: {state.last_posture or self.state_engine.explain_posture(state)}",
            f"  已观察消息: {state.messages_seen}",
            f"  最近事件: {state.last_event} ({state.last_event_reason or '无说明'})",
            f"  表达偏好: 长度={style.preferred_length}, 语气={style.preferred_tone}, 主动={style.preferred_initiative}",
        ]
        lm = "激活" if self.livingmemory.active else "未激活"
        lines.append(f"  LivingMemory: {lm}")
        yield event.plain_result("\n".join(lines))

    @filter.command("cp_profile")
    @filter.permission_type(PermissionType.ADMIN)
    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def cmd_profile(self, event: AstrMessageEvent):
        user_id = event.get_sender_id()
        state = await self._load_state_with_decay(user_id, save=True)
        style = await self._load_style(user_id)
        last_reflection = (
            time.strftime("%Y-%m-%d %H:%M", time.localtime(state.last_deep_reflection_at))
            if state.last_deep_reflection_at
            else "从未"
        )
        lines = [
            "=== 完整关系画像 ===",
            f"用户: {user_id}",
            f"关系阶段: {state.relationship_label()}",
            "",
            f"熟悉度: {state.familiarity:.1f}/100",
            f"亲近度: {state.closeness:.1f} (-50..100)",
            f"边界压力: {state.boundary_pressure:.1f}/100",
            f"能量: {state.energy:.1f}/90",
            f"边界姿态: {state.boundary_stance()}",
            f"当前回复姿态: {state.last_posture or self.state_engine.explain_posture(state)}",
            f"已观察消息: {state.messages_seen}",
            f"最近事件: {state.last_event}",
            f"最近事件原因: {state.last_event_reason or '-'}",
            f"最近反思摘要: {state.last_reflection_summary or '-'}",
            f"上次深度反思: {last_reflection}",
            "",
            f"偏好长度: {style.preferred_length}",
            f"偏好语气: {style.preferred_tone}",
            f"偏好主动: {style.preferred_initiative}",
        ]
        yield event.plain_result("\n".join(lines))

    @filter.command("cp_reset")
    @filter.permission_type(PermissionType.ADMIN)
    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def cmd_reset(self, event: AstrMessageEvent):
        user_id = event.get_sender_id()
        self.storage.clear_messages(user_id)
        self.storage.save_state(user_id, CompanionState(user_id=user_id).to_dict())
        self.storage.save_style_profile(user_id, StyleProfile(user_id=user_id).to_dict())
        yield event.plain_result(f"已重置关系状态: {user_id}")

    @filter.command("bond")
    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def cmd_bond(self, event: AstrMessageEvent):
        user_id = event.get_sender_id()
        if not self._is_main_user(user_id):
            yield event.plain_result("只有已配置的主用户可以建立陪伴模式。请先在 main_user_ids 中绑定该用户。")
            return
        state = await self._load_state_with_decay(user_id, save=False)
        cfg = self.plugin_config.basic
        state.bonded = True
        state.familiarity = max(state.familiarity, cfg.bond_familiarity_floor)
        state.closeness = max(state.closeness, cfg.bond_closeness_floor)
        state.boundary_pressure = min(state.boundary_pressure, cfg.bond_boundary_ceiling)
        state.last_event = "进入陪伴模式"
        state.last_event_reason = "/bond 进入陪伴模式：关系档位抬到熟人起步，精力不干涉，后续随互动自然演化"
        state.last_event_class = "manual_bond"
        state.last_gate_reason = "陪伴模式只抬关系档位，不碰精力——累了照样会话少"
        state.last_posture = self.state_engine.explain_posture(state)
        state.clamp()
        self._save_state(user_id, state)
        yield event.plain_result(
            f"已进入陪伴模式：{user_id}\n"
            f"起步档位：{state.relationship_label()}，亲近度 {state.closeness:.1f}。\n"
            f"精力不干涉——累了照样会话少。后续关系值和精力都会随对话自然变化。"
        )

    @filter.command("unbond")
    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def cmd_unbond(self, event: AstrMessageEvent):
        user_id = event.get_sender_id()
        if not self._is_main_user(user_id):
            yield event.plain_result("当前用户不是 CompanionLite 主用户，无需解除陪伴模式。")
            return
        state = await self._load_state_with_decay(user_id, save=False)
        was_bonded = state.bonded
        state.bonded = False
        state.last_event = "退出陪伴模式"
        state.last_event_reason = "/unbond 退出陪伴模式：保留当前关系值，回归自然积累"
        state.last_event_class = "manual_unbond"
        state.last_gate_reason = "陪伴模式已解除，数值保留现状由对话演化"
        state.last_posture = self.state_engine.explain_posture(state)
        state.clamp()
        self._save_state(user_id, state)
        self._last_injected_context_by_user.pop(user_id, None)
        if was_bonded:
            yield event.plain_result(
                f"已退出陪伴模式：{user_id}\n"
                f"当前关系：{state.relationship_label()}，亲近度 {state.closeness:.1f}。\n"
                f"关系值保留不变，后续完全由对话演化决定。"
            )
        else:
            yield event.plain_result(f"当前未处于陪伴模式：{user_id}，无需解除。")

    @filter.command("cp_silent")
    @filter.permission_type(PermissionType.ADMIN)
    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def cmd_silent(self, event: AstrMessageEvent):
        user_id = event.get_sender_id()
        state = await self._load_state(user_id)
        state.energy = 15.0
        state.mood = "疲惫"
        self._save_state(user_id, state)
        yield event.plain_result(f"已手动进入低能量模式: {user_id} (energy=15)")

    @staticmethod
    def _append_extra_user_content(req: Any, text: str) -> bool:
        parts = getattr(req, "extra_user_content_parts", None)
        if TextPart is None or parts is None or not hasattr(parts, "append"):
            return False
        try:
            part = TextPart(text=text)
            mark_as_temp = getattr(part, "mark_as_temp", None)
            if callable(mark_as_temp):
                part = mark_as_temp() or part
            parts.append(part)
            return True
        except Exception:
            return False

    PLUGIN_PREFIX = "/astrbot_plugin_companion_lite/page/debug"

    async def _resolve_user_id(self) -> str:
        return self.binding.primary_user_id()

    async def _api_state(self):
        user_id = await self._resolve_user_id()
        if not user_id:
            return json_response({"error": "no_bound_user"})
        state = await self._load_state_with_decay(user_id, save=True)
        result = state.to_dict()
        result["relationship_label"] = state.relationship_label()
        result["boundary_stance"] = state.boundary_stance()
        result["posture_explanation"] = state.last_posture or self.state_engine.explain_posture(state)
        result["silence_active"] = self.silence.check(state) is not None
        result["last_injected_context"] = self._last_injected_context_by_user.get(user_id, {})
        return json_response(result)

    async def _api_style(self):
        user_id = await self._resolve_user_id()
        if not user_id:
            return json_response({"error": "no_bound_user"})
        style = await self._load_style(user_id)
        return json_response(style.to_dict())

    async def _api_messages(self):
        user_id = await self._resolve_user_id()
        if not user_id:
            return json_response({"error": "no_bound_user"})
        limit = 20
        if request is not None:
            limit = request.query.get("limit", 20, type=int)
        raw_messages = self.storage.get_recent_messages(user_id, limit=limit)
        messages = [m for m in raw_messages if not self._is_system_command_text(str(m.get("content") or ""))]
        count = len(messages)
        return json_response({"messages": messages, "count": count})

    async def _api_health(self):
        user_id = await self._resolve_user_id()
        livingmemory_active = self.livingmemory.detect()
        return json_response(
            {
                "initialized": self._initialized,
                "binding_configured": self.binding.configured,
                "bound_user_ids": list(self.binding.user_ids),
                "capture_enabled": self.plugin_config.basic.enable_message_capture,
                "hook_enabled": self.plugin_config.basic.enable_llm_hook,
                "silence_enabled": self.plugin_config.basic.enable_silence,
                "reflection_enabled": self.plugin_config.basic.enable_deep_reflection,
                "livingmemory_active": livingmemory_active,
                "buffer_count": self.storage.count_messages(user_id) if user_id else 0,
                "last_reflection": self._last_reflection_ts,
                "background_tasks": len(self._background_tasks),
                "reflection_tasks": len(self._reflection_tasks_by_user),
            }
        )

    async def _api_reset(self):
        user_id = await self._resolve_user_id()
        if not user_id:
            return json_response({"error": "no_bound_user"})
        self.storage.clear_messages(user_id)
        self.storage.save_state(user_id, CompanionState(user_id=user_id).to_dict())
        self.storage.save_style_profile(user_id, StyleProfile(user_id=user_id).to_dict())
        return json_response({"ok": True, "user_id": user_id})

    async def _api_clear_messages(self):
        user_id = await self._resolve_user_id()
        if not user_id:
            return json_response({"error": "no_bound_user"})
        self.storage.clear_messages(user_id)
        return json_response({"ok": True})

    async def _api_clear_arcs(self):
        user_id = await self._resolve_user_id()
        if not user_id:
            return json_response({"error": "no_bound_user"})
        self.storage.clear_daily_arcs(user_id)
        return json_response({"ok": True})

    async def _api_trigger_reflection(self):
        user_id = await self._resolve_user_id()
        if not user_id:
            return json_response({"error": "no_bound_user"})
        state = await self._load_state(user_id)
        style = await self._load_style(user_id)
        messages = self._reflection_ready_messages(user_id, limit=20)
        if not messages:
            return json_response({"ok": True, "skipped": True, "reason": "no_messages"})
        queued = self._queue_reflection(user_id, state, style, messages)
        return json_response({"ok": True, "queued": queued, "message_count": len(messages)})

    async def _api_arc(self):
        user_id = await self._resolve_user_id()
        if not user_id:
            return json_response({"error": "no_bound_user"})
        state = await self._load_state(user_id)
        today_arc = self.arc_engine.get_today_arc(user_id)
        recent = self.arc_engine.get_recent_arcs(user_id, days=7)
        continuity_text = ""
        if self.plugin_config.continuity.enable_continuity_injection:
            try:
                continuity_text = self.arc_engine.build_continuity_text(
                    user_id, cycle_dominant=state.cycle_dominant_class
                )
            except Exception as exc:
                logger.warning("[CL] 连续性预览生成失败 user=%s: %s", user_id, exc)
        return json_response(
            {
                "today": today_arc,
                "recent": recent,
                "continuity_text": continuity_text,
                "continuity_enabled": self.plugin_config.continuity.enable_continuity_injection,
                "lookback_days": self.plugin_config.continuity.continuity_lookback_days,
                "arc_finalization_enabled": self.plugin_config.continuity.enable_arc_finalization,
            }
        )
