from __future__ import annotations

from astrbot_plugin_companion_lite.arc import ArcEngine
from astrbot_plugin_companion_lite.core import CompanionState, InteractionEvent, StateEngine, Storage


def _state(**kwargs) -> CompanionState:
    defaults = {"user_id": "u1", "energy": 60.0, "safety": 55.0}
    defaults.update(kwargs)
    return CompanionState(**defaults)


def _apply_and_record(
    arc_engine: ArcEngine,
    state_engine: StateEngine,
    state: CompanionState,
    event: InteractionEvent,
    now: float,
) -> None:
    before = arc_engine.state_snapshot(state)
    update = state_engine.apply_event(state, event, now=now)
    arc_engine.record_event("u1", before, state, event, update.deltas, now=now)


def test_session_crosses_midnight_when_gap_is_short(tmp_path):
    storage = Storage(str(tmp_path / "session.db"))
    try:
        arcs = ArcEngine(storage)
        engine = StateEngine()
        state = _state()
        start = 1_800_000_000.0
        _apply_and_record(arcs, engine, state, InteractionEvent("neutral"), start)
        _apply_and_record(arcs, engine, state, InteractionEvent("neutral"), start + 30 * 60)
        sessions = storage.get_recent_session_arcs("u1")
        assert len(sessions) == 1
        assert sessions[0]["message_count"] == 2
        assert sessions[0]["status"] == "open"
    finally:
        storage.close()


def test_idle_gap_closes_old_session_and_opens_new_one(tmp_path):
    storage = Storage(str(tmp_path / "split.db"))
    try:
        arcs = ArcEngine(storage)
        engine = StateEngine()
        state = _state()
        start = 1_800_000_000.0
        _apply_and_record(arcs, engine, state, InteractionEvent("neutral"), start)
        _apply_and_record(arcs, engine, state, InteractionEvent("neutral"), start + 61 * 60)
        sessions = storage.get_recent_session_arcs("u1")
        assert len(sessions) == 2
        assert sessions[0]["status"] == "open"
        assert sessions[1]["status"] == "closed"
    finally:
        storage.close()


def test_boundary_then_repair_preserves_both_turning_points(tmp_path):
    storage = Storage(str(tmp_path / "turns.db"))
    try:
        arcs = ArcEngine(storage)
        engine = StateEngine()
        state = _state()
        start = 1_800_000_000.0
        _apply_and_record(
            arcs,
            engine,
            state,
            InteractionEvent("boundary_push", "boundary_violation", "stop", intensity=1.5),
            start,
        )
        _apply_and_record(arcs, engine, state, InteractionEvent("apology", "repair", "sorry"), start + 600)
        closed = arcs.close_idle_session("u1", state, now=start + 5000)
        assert closed is not None
        assert [point["kind"] for point in closed["turning_points"]] == ["boundary_escalation", "repair_attempt"]
        assert closed["outcome"] in {"partial_repair", "recovered"}
    finally:
        storage.close()


def test_session_continuity_uses_rule_outcome(tmp_path):
    storage = Storage(str(tmp_path / "continuity.db"))
    try:
        arcs = ArcEngine(storage)
        state = _state(boundary_pressure=30.0)
        now = 1_800_000_000.0
        arc = storage.create_session_arc("u1", arcs.state_snapshot(_state()), now)
        arc["turning_points"] = [{"kind": "boundary_escalation", "at": now}]
        arc["peak_boundary_pressure"] = 30.0
        arc["end_snapshot"] = arcs.state_snapshot(state)
        storage.update_session_arc(arc["id"], arc)
        arcs.close_idle_session("u1", state, now=now + 4000)
        text = arcs.build_continuity_text("u1")
        assert "紧张" in text
        assert "少追问" in text
    finally:
        storage.close()


def test_explicit_profile_overrides_previous_value(tmp_path):
    storage = Storage(str(tmp_path / "profile.db"))
    try:
        arcs = ArcEngine(storage)
        arcs.record_explicit_profile("u1", "style_length_short", now=100.0)
        arcs.record_explicit_profile("u1", "style_length_long", now=200.0)
        evidence = storage.get_profile_evidence("u1")
        assert len(evidence) == 1
        assert evidence[0]["profile_value"] == "long"
        assert evidence[0]["confidence"] == 1.0
        assert "详细" in arcs.build_profile_text("u1")
    finally:
        storage.close()


def test_reflection_updates_summary_not_outcome(tmp_path):
    storage = Storage(str(tmp_path / "reflection.db"))
    try:
        arcs = ArcEngine(storage)
        arc = storage.create_session_arc("u1", arcs.state_snapshot(_state()), 100.0)
        arcs.update_session_from_reflection("u1", {"reflection_summary": "用户先拒绝后解释"})
        updated = storage.get_session_arc(arc["id"])
        assert updated["summary"] == "用户先拒绝后解释"
        assert updated["outcome"] == "ongoing"
        assert updated["reflection_count"] == 1
    finally:
        storage.close()
