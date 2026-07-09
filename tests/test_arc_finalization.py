from __future__ import annotations

import os
import time
import asyncio
import tempfile

import pytest

from astrbot_plugin_companion_lite.arc import ArcEngine
from astrbot_plugin_companion_lite.state import CompanionState
from astrbot_plugin_companion_lite.storage import Storage


@pytest.fixture
def storage(tmp_path):
    path = str(tmp_path / "test_arc.db")
    s = Storage(path)
    yield s
    s.close()


def _make_state(**kwargs) -> CompanionState:
    defaults = dict(user_id="u1", familiarity=30.0, closeness=20.0)
    defaults.update(kwargs)
    return CompanionState(**defaults)


def _reflection_result(guidance: str = "", mood: str = "白天轻松", trend: str = "稳定") -> dict:
    return {
        "arc_mood": mood,
        "arc_trend": trend,
        "arc_highlights": ["聊了工作", "开了个玩笑"],
        "tomorrow_guidance": guidance,
    }


def _yesterday() -> str:
    return time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))


def _today() -> str:
    return time.strftime("%Y-%m-%d")


class TestArcAccumulation:
    def test_segments_accumulate_not_overwrite(self, storage):
        engine = ArcEngine(storage, llm_request_func=None)
        state = _make_state()
        engine.update_from_reflection("u1", _reflection_result("建议A"), state)
        engine.update_from_reflection("u1", _reflection_result("建议B"), state)
        arc = storage.get_daily_arc("u1", _today())
        assert arc is not None
        assert arc["guidance_segments"] == ["建议A", "建议B"]
        assert arc["cycle_count"] == 2
        assert arc["finalized"] is False

    def test_midday_compress_triggers(self, storage):
        engine = ArcEngine(storage, llm_request_func=None, midday_compress_threshold=3, max_segments=5)
        state = _make_state()
        for i in range(3):
            engine.update_from_reflection("u1", _reflection_result(f"建议{i}"), state)
        arc = storage.get_daily_arc("u1", _today())
        assert len(arc["guidance_segments"]) <= 2


class TestArcFinalization:
    def test_finalize_without_llm_uses_last_segment(self, storage):
        engine = ArcEngine(storage, llm_request_func=None)
        state = _make_state()
        engine.update_from_reflection("u1", _reflection_result("建议A"), state)
        engine.update_from_reflection("u1", _reflection_result("建议B"), state)
        ok = asyncio.run(engine.finalize_arc_for_date("u1", _today()))
        assert ok is True
        arc = storage.get_daily_arc("u1", _today())
        assert arc["finalized"] is True
        assert arc["tomorrow_guidance"] == "建议B"

    def test_finalize_with_llm_compresses(self, storage):
        async def fake_llm(prompt: str, system_prompt: str = "", provider_id: str = "") -> str:
            return "压缩后的明日建议"

        engine = ArcEngine(storage, llm_request_func=fake_llm)
        state = _make_state()
        engine.update_from_reflection("u1", _reflection_result("建议A"), state)
        engine.update_from_reflection("u1", _reflection_result("建议B"), state)
        asyncio.run(engine.finalize_arc_for_date("u1", _today()))
        arc = storage.get_daily_arc("u1", _today())
        assert arc["finalized"] is True
        assert arc["tomorrow_guidance"] == "压缩后的明日建议"

    def test_double_finalize_idempotent(self, storage):
        engine = ArcEngine(storage, llm_request_func=None)
        state = _make_state()
        engine.update_from_reflection("u1", _reflection_result("建议A"), state)
        asyncio.run(engine.finalize_arc_for_date("u1", _today()))
        ok = asyncio.run(engine.finalize_arc_for_date("u1", _today()))
        assert ok is False


class TestContinuityGuard:
    def test_unfinalized_yesterday_not_injected_guidance(self, storage):
        """昨天的未 finalize 弧线，guidance 不注入，但 mood 可以注入。"""
        engine = ArcEngine(storage, llm_request_func=None)
        state = _make_state()
        yesterday = _yesterday()
        storage.upsert_daily_arc("u1", yesterday, {
            "overall_mood": "轻松",
            "relationship_trend": "靠近",
            "tomorrow_guidance": "建议A",
            "finalized": False,
            "guidance_segments": ["建议A"],
        })
        text = engine.build_continuity_text("u1")
        assert "建议A" not in text
        assert "轻松" in text

    def test_finalized_yesterday_injected(self, storage):
        async def fake_llm(prompt: str, system_prompt: str = "", provider_id: str = "") -> str:
            return "明天开场轻柔"

        engine = ArcEngine(storage, llm_request_func=fake_llm)
        state = _make_state()
        yesterday = _yesterday()
        storage.upsert_daily_arc("u1", yesterday, {
            "overall_mood": "轻松",
            "relationship_trend": "靠近",
            "tomorrow_guidance": "",
            "finalized": False,
            "guidance_segments": ["建议A"],
        })
        asyncio.run(engine.finalize_arc_for_date("u1", yesterday))
        text = engine.build_continuity_text("u1")
        assert "明天开场轻柔" in text


class TestStorageMigration:
    def test_old_arc_row_has_new_defaults(self, storage):
        cur = storage._conn.cursor()
        cur.execute(
            "INSERT INTO daily_arc (user_id, date, overall_mood, relationship_trend, "
            "important_interactions, tomorrow_guidance, source, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("u1", _today(), "mood", "trend", "[]", "g", "local", 0.0),
        )
        storage._conn.commit()
        arc = storage.get_daily_arc("u1", _today())
        assert arc["guidance_segments"] == []
        assert arc["finalized"] is False
        assert arc["cycle_count"] == 0

    def test_get_unfinalized_before_returns_oldest_unfinalized(self, storage):
        storage.upsert_daily_arc("u1", "2026-07-01", {"overall_mood": "m", "finalized": False})
        storage.upsert_daily_arc("u1", "2026-07-02", {"overall_mood": "m", "finalized": True})
        # 07-03 之前：07-02 已 finalize，07-01 未 finalize → 返回 07-01
        stale = storage.get_unfinalized_arc_before("u1", "2026-07-03")
        assert stale is not None
        assert stale["date"] == "2026-07-01"
        # 07-02 之前：07-01 未 finalize → 仍返回 07-01（不是 None）
        still = storage.get_unfinalized_arc_before("u1", "2026-07-02")
        assert still is not None
        assert still["date"] == "2026-07-01"
        # 07-01 之前：无数据 → None
        none_case = storage.get_unfinalized_arc_before("u1", "2026-07-01")
        assert none_case is None
