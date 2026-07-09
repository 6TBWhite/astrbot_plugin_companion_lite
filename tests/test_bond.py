from __future__ import annotations

from astrbot_plugin_companion_lite.state import CompanionState


class TestBondField:
    def test_default_not_bonded(self):
        state = CompanionState(user_id="u1")
        assert state.bonded is False

    def test_bonded_persisted_via_to_from_dict(self):
        state = CompanionState(user_id="u1", bonded=True, familiarity=60.0, closeness=55.0)
        data = state.to_dict()
        assert data["bonded"] is True
        restored = CompanionState.from_dict(data)
        assert restored.bonded is True

    def test_old_data_without_bonded_defaults_false(self):
        data = {"user_id": "u1", "familiarity": 50.0}
        state = CompanionState.from_dict(data)
        assert state.bonded is False
