from __future__ import annotations

import asyncio
import time

from astrbot_plugin_companion_lite.core import StateEngine, Storage
from astrbot_plugin_companion_lite.main import CompanionLitePlugin


def _plugin_with_storage(db_path: str) -> CompanionLitePlugin:
    plugin = object.__new__(CompanionLitePlugin)
    plugin.storage = Storage(db_path)
    plugin.state_engine = StateEngine()
    return plugin


def test_first_state_load_is_persisted(tmp_path):
    plugin = _plugin_with_storage(str(tmp_path / "initial.db"))

    state = asyncio.run(plugin._load_state("bound-user"))

    stored = plugin.storage.get_state("bound-user")
    assert stored is not None
    assert stored["energy"] == 60.0
    assert stored["last_state_updated_at"] == state.last_state_updated_at


def test_bound_user_without_messages_accumulates_natural_recovery(tmp_path):
    plugin = _plugin_with_storage(str(tmp_path / "recovery.db"))
    state = asyncio.run(plugin._load_state("bound-user"))
    state.last_state_updated_at = time.time() - 20 * 60
    plugin._save_state("bound-user", state)

    recovered = asyncio.run(plugin._load_state_with_decay("bound-user", save=True))

    assert recovered.energy > 60.6
    assert plugin.storage.get_state("bound-user")["energy"] > 60.6
