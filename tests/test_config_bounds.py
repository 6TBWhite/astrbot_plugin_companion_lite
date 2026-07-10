from __future__ import annotations

from astrbot_plugin_companion_lite.config import load_config


def test_reflection_idle_default_is_40_minutes():
    reflection = load_config({}).reflection
    assert reflection.reflection_message_interval == 10
    assert reflection.reflection_time_interval_minutes == 40


def test_silence_thresholds_are_bounded():
    config = load_config(
        {
            "Silence_Settings": {
                "silence_energy_threshold": 999,
                "silence_boundary_threshold": -5,
            }
        }
    )
    assert config.silence.energy_threshold == 90
    assert config.silence.boundary_threshold == 0
