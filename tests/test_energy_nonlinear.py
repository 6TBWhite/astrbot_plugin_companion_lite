from __future__ import annotations

import time

from astrbot_plugin_companion_lite.state import CompanionState
from astrbot_plugin_companion_lite.state_engine import StateEngine
from astrbot_plugin_companion_lite.events import InteractionEvent
from astrbot_plugin_companion_lite.context_builder import ContextBuilder


def _make_state(energy: float = 60.0, **kwargs) -> CompanionState:
    defaults = dict(user_id="u1", energy=energy)
    defaults.update(kwargs)
    return CompanionState(**defaults)


class TestEnergyNaturalDecay:
    def test_high_energy_decreases(self):
        engine = StateEngine()
        state = _make_state(energy=85.0)
        state.last_state_updated_at = time.time() - 3600
        applied = engine.apply_time_decay(state)
        assert "energy" in applied
        assert applied["energy"] < 0
        assert state.energy < 85.0

    def test_high_energy_toward_65(self):
        engine = StateEngine()
        state = _make_state(energy=85.0)
        state.last_state_updated_at = time.time() - 3600 * 10
        engine.apply_time_decay(state)
        assert state.energy >= 65.0 - 1.0
        assert state.energy < 80.0

    def test_midhigh_energy_recover_toward_70(self):
        engine = StateEngine()
        state = _make_state(energy=58.0)
        state.last_state_updated_at = time.time() - 3600 * 2
        applied = engine.apply_time_decay(state)
        assert applied.get("energy", 0) > 0
        assert state.energy > 58.0

    def test_low_energy_slowl_recovery(self):
        engine = StateEngine()
        state = _make_state(energy=20.0)
        state.last_state_updated_at = time.time() - 3600
        applied = engine.apply_time_decay(state)
        recovered = applied.get("energy", 0.0)
        assert 0 < recovered <= 0.5
        assert state.energy < 22.0

    def test_low_energy_stays_low_long_time(self):
        engine = StateEngine()
        state = _make_state(energy=20.0)
        state.last_state_updated_at = time.time() - 3600 * 5
        engine.apply_time_decay(state)
        assert state.energy < 33.0

    def test_high_energy_decays_even_short_interval(self):
        """高频聊天（间隔 <3分钟）时，高能区能量仍应衰减，不被防抖门槛冻住。"""
        engine = StateEngine()
        state = _make_state(energy=74.0)
        state.last_state_updated_at = time.time() - 30  # 30 秒前
        applied = engine.apply_time_decay(state)
        assert "energy" in applied
        assert applied["energy"] < 0
        assert state.energy < 74.0


class TestEnergyEventTier:
    def test_high_energy_event_consumption_doubled(self):
        engine = StateEngine()
        state = _make_state(energy=85.0)
        event = InteractionEvent("active_chat", "neutral", "test")
        update = engine.apply_event(state, event)
        assert update.deltas.get("energy", 0) <= -2.0

    def test_low_energy_event_consumption_light(self):
        engine = StateEngine()
        state = _make_state(energy=20.0)
        event = InteractionEvent("active_chat", "neutral", "test")
        update = engine.apply_event(state, event)
        consumed = update.deltas.get("energy", 0)
        assert consumed > -1.0

    def test_positive_energy_full_recovery_when_low(self):
        engine = StateEngine()
        state = _make_state(energy=20.0)
        event = InteractionEvent("rest_request", "withdrawal", "test")
        update = engine.apply_event(state, event)
        assert update.deltas.get("energy", 0) > 0

    def test_positive_energy_zero_when_high(self):
        """高能区不再被正向事件推高——已经够精神了。高频微消耗仍会扣一点。"""
        engine = StateEngine()
        state = _make_state(energy=74.0)
        event = InteractionEvent("gratitude", "prosocial", "test")
        update = engine.apply_event(state, event)
        # 正向回血归零，但高频微消耗可能扣一点，所以是 <=0 不再是 ==0
        assert update.deltas.get("energy", 0) <= 0

    def test_positive_energy_partial_when_midhigh(self):
        """中高区正向回血大幅削减(×0.3)，高频微消耗可能再扣一点，净效果应接近0或微正。"""
        engine = StateEngine()
        state = _make_state(energy=60.0)
        # 设远间隔避免高频微消耗干扰，单独验证分段系数
        state.last_state_updated_at = time.time() - 200
        event = InteractionEvent("gratitude", "prosocial", "test")
        update = engine.apply_event(state, event)
        gained = update.deltas.get("energy", 0)
        assert 0 < gained < 1.0


class TestActiveChatDrain:
    def test_high_freq_chat_drains_energy(self):
        """连续密集消息（间隔 <2分钟）时，每条额外扣精力。"""
        engine = StateEngine()
        state = _make_state(energy=72.0)
        state.last_state_updated_at = time.time() - 10  # 10秒前
        event = InteractionEvent("neutral", "neutral", "test")
        update = engine.apply_event(state, event)
        energy_delta = update.deltas.get("energy", 0)
        # neutral 事件本身不碰 energy，所以负值完全来自高频微消耗
        assert energy_delta < 0

    def test_low_freq_chat_no_extra_drain(self):
        """间隔 >2分钟的消息不触发高频微消耗。"""
        engine = StateEngine()
        state = _make_state(energy=72.0)
        state.last_state_updated_at = time.time() - 180  # 3分钟前
        event = InteractionEvent("neutral", "neutral", "test")
        update = engine.apply_event(state, event)
        energy_delta = update.deltas.get("energy", 0)
        # neutral 事件不碰 energy，间隔又超过窗口，不该有 energy 变化
        assert energy_delta == 0

    def test_low_energy_no_extra_drain(self):
        """开摆区(<=30)不额外扣——累了就不追着扣了。"""
        engine = StateEngine()
        state = _make_state(energy=25.0)
        state.last_state_updated_at = time.time() - 10
        event = InteractionEvent("neutral", "neutral", "test")
        update = engine.apply_event(state, event)
        energy_delta = update.deltas.get("energy", 0)
        assert energy_delta == 0

    def test_40_messages_expected_drain(self):
        """40条密集消息期望掉约12-24点（uniform 0.30-0.60 × 40）。"""
        engine = StateEngine()
        state = _make_state(energy=75.0)
        start_energy = state.energy
        for _ in range(40):
            state.last_state_updated_at = time.time() - 5  # 每条间隔5秒
            event = InteractionEvent("neutral", "neutral", "test")
            engine.apply_event(state, event)
        total_drain = start_energy - state.energy
        # 40 × uniform(0.30, 0.60) 理论范围 12-24，期望 18
        assert total_drain >= 10.0, f"总消耗{total_drain}低于下界预期"


class TestEnergyTransmission:
    def test_energy_text_five_tiers(self):
        assert "已经累了" in ContextBuilder._energy_text(25)
        assert "有点累" in ContextBuilder._energy_text(38)
        assert "普通" in ContextBuilder._energy_text(50)
        assert "状态不错" in ContextBuilder._energy_text(62)
        assert "很有精神" in ContextBuilder._energy_text(69)

    def test_posture_has_42_tier(self):
        engine = StateEngine()
        state = _make_state(energy=38.0, closeness=50.0, boundary_pressure=10.0)
        posture = engine.explain_posture(state)
        assert "微疲" in posture


class TestReflectionEnergyTier:
    """反思路径的 energy delta 也要走分段调制，且正向有独立上限。"""

    def test_reflection_positive_capped_when_high(self):
        """反思给 +10，高能区被分段×0.0 归零——堵"喝红牛"。"""
        engine = StateEngine()
        state = _make_state(energy=74.0)
        result = {"energy_delta": 10.0}
        applied = engine.apply_reflection_delta(state, result)
        assert applied.get("energy", 0) == 0

    def test_reflection_positive_capped_at_two(self):
        """反思正向 energy delta 上限 +2，即使低能区全额回血也最多 +2。"""
        engine = StateEngine()
        state = _make_state(energy=20.0)
        result = {"energy_delta": 10.0}
        applied = engine.apply_reflection_delta(state, result)
        # 低能区正向系数 ×1.0，但先被 cap 到 +2
        assert applied.get("energy", 0) == 2.0

    def test_reflection_negative_not_capped(self):
        """反思负向 energy delta 不受 +2 上限影响，-8 原样生效（分段调制后）。"""
        engine = StateEngine()
        state = _make_state(energy=65.0)
        result = {"energy_delta": -8.0}
        applied = engine.apply_reflection_delta(state, result)
        # 中高区负向 ×1.0，-8 原样
        assert applied.get("energy", 0) <= -7.0

    def test_reflection_positive_partial_midhigh(self):
        """中高区反思正向 +2 被分段 ×0.3 削减到 +0.6。"""
        engine = StateEngine()
        state = _make_state(energy=60.0)
        result = {"energy_delta": 5.0}
        applied = engine.apply_reflection_delta(state, result)
        gained = applied.get("energy", 0)
        assert 0 < gained < 1.0
