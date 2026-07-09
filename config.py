from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BasicSettings:
    enable_message_capture: bool = True
    enable_llm_hook: bool = True
    enable_silence: bool = True
    enable_deep_reflection: bool = True
    main_user_ids: list[str] = field(default_factory=list)
    log_level: str = "info"
    min_message_length: int = 2
    max_message_length: int = 500
    max_buffer_messages: int = 120
    recent_rate_window_seconds: int = 60
    bond_familiarity_floor: float = 55.0
    bond_closeness_floor: float = 50.0
    bond_boundary_ceiling: float = 15.0


@dataclass
class ReflectionSettings:
    reflection_message_interval: int = 12
    reflection_time_interval_minutes: int = 30


@dataclass
class ContinuitySettings:
    enable_continuity_injection: bool = True
    continuity_lookback_days: int = 3
    enable_arc_finalization: bool = True
    arc_midday_compress_threshold: int = 4
    arc_max_segments: int = 5


@dataclass
class SilenceSettings:
    energy_threshold: int = 25
    boundary_threshold: int = 60


@dataclass
class LivingMemorySettings:
    delegate_memory_to_livingmemory: bool = True
    livingmemory_plugin_name: str = "LivingMemory"


@dataclass
class LLMSettings:
    reflection_provider_id: str = ""
    max_context_chars: int = 900


@dataclass
class CLConfig:
    basic: BasicSettings = field(default_factory=BasicSettings)
    reflection: ReflectionSettings = field(default_factory=ReflectionSettings)
    continuity: ContinuitySettings = field(default_factory=ContinuitySettings)
    silence: SilenceSettings = field(default_factory=SilenceSettings)
    livingmemory: LivingMemorySettings = field(default_factory=LivingMemorySettings)
    llm: LLMSettings = field(default_factory=LLMSettings)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CLConfig:
        basic_raw = _group(raw, "Basic_Settings")
        reflection_raw = _group(raw, "Reflection_Settings")
        continuity_raw = _group(raw, "Continuity_Settings")
        silence_raw = _group(raw, "Silence_Settings")
        livingmemory_raw = _group(raw, "LivingMemory_Settings")
        llm_raw = _group(raw, "LLM_Settings")
        basic = BasicSettings(
            enable_message_capture=_bool(_get(raw, basic_raw, "enable_message_capture", True), True),
            enable_llm_hook=_bool(_get(raw, basic_raw, "enable_llm_hook", True), True),
            enable_silence=_bool(_get(raw, basic_raw, "enable_silence", True), True),
            enable_deep_reflection=_bool(_get(raw, basic_raw, "enable_deep_reflection", True), True),
            main_user_ids=_normalize_user_ids(_get(raw, basic_raw, "main_user_ids", [])),
            log_level=str(_get(raw, basic_raw, "log_level", "info") or "info"),
            min_message_length=max(0, _int(_get(raw, basic_raw, "min_message_length", 2), 2)),
            max_message_length=max(1, _int(_get(raw, basic_raw, "max_message_length", 500), 500)),
            max_buffer_messages=max(20, _int(_get(raw, basic_raw, "max_buffer_messages", 120), 120)),
            recent_rate_window_seconds=max(10, _int(_get(raw, basic_raw, "recent_rate_window_seconds", 60), 60)),
            bond_familiarity_floor=_float(_get(raw, basic_raw, "bond_familiarity_floor", 55.0), 55.0),
            bond_closeness_floor=_float(_get(raw, basic_raw, "bond_closeness_floor", 50.0), 50.0),
            bond_boundary_ceiling=_float(_get(raw, basic_raw, "bond_boundary_ceiling", 15.0), 15.0),
        )
        reflection = ReflectionSettings(
            reflection_message_interval=max(
                1, _int(_get(raw, reflection_raw, "reflection_message_interval", 12), 12)
            ),
            reflection_time_interval_minutes=max(
                0, _int(_get(raw, reflection_raw, "reflection_time_interval_minutes", 30), 30)
            ),
        )
        continuity = ContinuitySettings(
            enable_continuity_injection=_bool(
                _get(raw, continuity_raw, "enable_continuity_injection", True), True
            ),
            continuity_lookback_days=max(
                1, min(7, _int(_get(raw, continuity_raw, "continuity_lookback_days", 3), 3))
            ),
            enable_arc_finalization=_bool(
                _get(raw, continuity_raw, "enable_arc_finalization", True), True
            ),
            arc_midday_compress_threshold=max(
                0, _int(_get(raw, continuity_raw, "arc_midday_compress_threshold", 4), 4)
            ),
            arc_max_segments=max(
                1, _int(_get(raw, continuity_raw, "arc_max_segments", 5), 5)
            ),
        )
        silence = SilenceSettings(
            energy_threshold=_int(_get(raw, silence_raw, "silence_energy_threshold", 25), 25),
            boundary_threshold=_int(_get(raw, silence_raw, "silence_boundary_threshold", 60), 60),
        )
        livingmemory = LivingMemorySettings(
            delegate_memory_to_livingmemory=_bool(
                _get(raw, livingmemory_raw, "delegate_memory_to_livingmemory", True), True
            ),
            livingmemory_plugin_name=str(
                _get(raw, livingmemory_raw, "livingmemory_plugin_name", "LivingMemory") or "LivingMemory"
            ),
        )
        llm = LLMSettings(
            reflection_provider_id=str(_get(raw, llm_raw, "reflection_provider_id", "") or ""),
            max_context_chars=max(100, _int(_get(raw, llm_raw, "max_context_chars", 900), 900)),
        )
        return cls(
            basic=basic,
            reflection=reflection,
            continuity=continuity,
            silence=silence,
            livingmemory=livingmemory,
            llm=llm,
        )


def load_config(raw: dict[str, Any]) -> CLConfig:
    return CLConfig.from_dict(raw)


def _group(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name, {}) if isinstance(raw, dict) else {}
    return value if isinstance(value, dict) else {}


def _get(raw: dict[str, Any], group: dict[str, Any], key: str, default: Any) -> Any:
    if key in group:
        return group[key]
    return raw.get(key, default) if isinstance(raw, dict) else default


def _bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on", "是", "开启"}:
            return True
        if lowered in {"false", "0", "no", "off", "否", "关闭"}:
            return False
    return default


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_user_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = value.replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
