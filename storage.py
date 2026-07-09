from __future__ import annotations

import json
import os
import sqlite3
import time

from typing import Any


class Storage:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self) -> None:
        cur = self._conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS companion_state (
                user_id TEXT PRIMARY KEY,
                state TEXT NOT NULL DEFAULT '{}',
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS style_profile (
                user_id TEXT PRIMARY KEY,
                profile TEXT NOT NULL DEFAULT '{}',
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS message_buffer (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_buffer_user ON message_buffer(user_id, timestamp);
            CREATE TABLE IF NOT EXISTS daily_arc (
                user_id TEXT NOT NULL,
                date TEXT NOT NULL,
                overall_mood TEXT DEFAULT '',
                relationship_trend TEXT DEFAULT '',
                important_interactions TEXT DEFAULT '[]',
                tomorrow_guidance TEXT DEFAULT '',
                source TEXT DEFAULT 'local',
                updated_at REAL DEFAULT 0,
                PRIMARY KEY (user_id, date)
            );
        """)
        self._migrate_daily_arc_columns(cur)
        self._conn.commit()

    def _migrate_daily_arc_columns(self, cur) -> None:
        """为老库补齐 guidance_segments / finalized / cycle_count 字段。"""
        existing = {row[1] for row in cur.execute("PRAGMA table_info(daily_arc)").fetchall()}
        if "guidance_segments" not in existing:
            cur.execute("ALTER TABLE daily_arc ADD COLUMN guidance_segments TEXT DEFAULT '[]'")
        if "finalized" not in existing:
            cur.execute("ALTER TABLE daily_arc ADD COLUMN finalized INTEGER DEFAULT 0")
        if "cycle_count" not in existing:
            cur.execute("ALTER TABLE daily_arc ADD COLUMN cycle_count INTEGER DEFAULT 0")

    def get_state(self, user_id: str) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        cur.execute("SELECT state FROM companion_state WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        return json.loads(row["state"]) if row else None

    def save_state(self, user_id: str, state_dict: dict[str, Any]) -> None:
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO companion_state (user_id, state, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET state = excluded.state, updated_at = excluded.updated_at",
            (user_id, json.dumps(state_dict, ensure_ascii=False), now),
        )
        self._conn.commit()

    def get_style_profile(self, user_id: str) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        cur.execute("SELECT profile FROM style_profile WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        return json.loads(row["profile"]) if row else None

    def save_style_profile(self, user_id: str, profile_dict: dict[str, Any]) -> None:
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO style_profile (user_id, profile, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET profile = excluded.profile, updated_at = excluded.updated_at",
            (user_id, json.dumps(profile_dict, ensure_ascii=False), now),
        )
        self._conn.commit()

    def append_message(self, user_id: str, role: str, content: str, max_messages: int | None = None) -> None:
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO message_buffer (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, role, content, now),
        )
        self._conn.commit()
        if max_messages is not None:
            self.trim_messages(user_id, max_messages)

    def get_recent_messages(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT role, content, timestamp FROM message_buffer WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
            (user_id, limit),
        )
        rows = cur.fetchall()
        return [{"role": r["role"], "content": r["content"], "timestamp": r["timestamp"]} for r in reversed(rows)]

    def clear_messages(self, user_id: str) -> None:
        cur = self._conn.cursor()
        cur.execute("DELETE FROM message_buffer WHERE user_id = ?", (user_id,))
        self._conn.commit()

    def trim_messages(self, user_id: str, max_messages: int) -> None:
        if max_messages <= 0:
            return
        cur = self._conn.cursor()
        cur.execute(
            "DELETE FROM message_buffer WHERE user_id = ? AND id NOT IN ("
            "SELECT id FROM message_buffer WHERE user_id = ? ORDER BY timestamp DESC, id DESC LIMIT ?"
            ")",
            (user_id, user_id, max_messages),
        )
        self._conn.commit()

    def count_messages(self, user_id: str) -> int:
        cur = self._conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM message_buffer WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        return row["cnt"] if row else 0

    def count_recent_user_messages(self, user_id: str, window_seconds: int) -> int:
        since = time.time() - max(1, window_seconds)
        cur = self._conn.cursor()
        cur.execute(
            "SELECT COUNT(*) as cnt FROM message_buffer WHERE user_id = ? AND role = 'user' AND timestamp >= ?",
            (user_id, since),
        )
        row = cur.fetchone()
        return row["cnt"] if row else 0

    def get_oldest_timestamp(self, user_id: str) -> float | None:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT MIN(timestamp) as ts FROM message_buffer WHERE user_id = ?",
            (user_id,),
        )
        row = cur.fetchone()
        return row["ts"] if row and row["ts"] else None

    def upsert_daily_arc(self, user_id: str, date: str, arc: dict[str, Any]) -> None:
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO daily_arc (user_id, date, overall_mood, relationship_trend, "
            "important_interactions, tomorrow_guidance, source, updated_at, "
            "guidance_segments, finalized, cycle_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, date) DO UPDATE SET "
            "overall_mood = excluded.overall_mood, "
            "relationship_trend = excluded.relationship_trend, "
            "important_interactions = excluded.important_interactions, "
            "tomorrow_guidance = excluded.tomorrow_guidance, "
            "source = excluded.source, "
            "updated_at = excluded.updated_at, "
            "guidance_segments = excluded.guidance_segments, "
            "finalized = excluded.finalized, "
            "cycle_count = excluded.cycle_count",
            (
                user_id,
                date,
                str(arc.get("overall_mood", "")),
                str(arc.get("relationship_trend", "")),
                json.dumps(arc.get("important_interactions", []), ensure_ascii=False),
                str(arc.get("tomorrow_guidance", "")),
                str(arc.get("source", "local")),
                time.time(),
                json.dumps(arc.get("guidance_segments", []), ensure_ascii=False),
                int(bool(arc.get("finalized", False))),
                int(arc.get("cycle_count", 0)),
            ),
        )
        self._conn.commit()

    def get_daily_arc(self, user_id: str, date: str) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM daily_arc WHERE user_id = ? AND date = ?", (user_id, date))
        row = cur.fetchone()
        return self._arc_row_to_dict(row) if row else None

    def get_recent_arcs(self, user_id: str, days: int = 3, before_date: str = "") -> list[dict[str, Any]]:
        """按日期降序返回 before_date（不含）之前最近 N 天的弧线。"""
        cur = self._conn.cursor()
        if before_date:
            cur.execute(
                "SELECT * FROM daily_arc WHERE user_id = ? AND date < ? ORDER BY date DESC LIMIT ?",
                (user_id, before_date, max(1, days)),
            )
        else:
            cur.execute(
                "SELECT * FROM daily_arc WHERE user_id = ? ORDER BY date DESC LIMIT ?",
                (user_id, max(1, days)),
            )
        return [self._arc_row_to_dict(row) for row in cur.fetchall()]

    def get_unfinalized_arc_before(self, user_id: str, date: str) -> dict[str, Any] | None:
        """返回指定日期之前最近一条未 finalized 的弧线，用于跨天补生成。"""
        cur = self._conn.cursor()
        cur.execute(
            "SELECT * FROM daily_arc WHERE user_id = ? AND date < ? AND finalized = 0 "
            "ORDER BY date DESC LIMIT 1",
            (user_id, date),
        )
        row = cur.fetchone()
        return self._arc_row_to_dict(row) if row else None

    def clear_daily_arcs(self, user_id: str) -> None:
        cur = self._conn.cursor()
        cur.execute("DELETE FROM daily_arc WHERE user_id = ?", (user_id,))
        self._conn.commit()

    @staticmethod
    def _arc_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        try:
            interactions = json.loads(row["important_interactions"] or "[]")
        except (json.JSONDecodeError, TypeError):
            interactions = []
        try:
            segments = json.loads(row["guidance_segments"] or "[]")
        except (json.JSONDecodeError, TypeError, KeyError):
            segments = []
        finalized = False
        try:
            finalized = bool(int(row["finalized"] or 0))
        except (KeyError, TypeError, ValueError):
            pass
        cycle_count = 0
        try:
            cycle_count = int(row["cycle_count"] or 0)
        except (KeyError, TypeError, ValueError):
            pass
        return {
            "user_id": row["user_id"],
            "date": row["date"],
            "overall_mood": row["overall_mood"] or "",
            "relationship_trend": row["relationship_trend"] or "",
            "important_interactions": interactions if isinstance(interactions, list) else [],
            "tomorrow_guidance": row["tomorrow_guidance"] or "",
            "source": row["source"] or "local",
            "updated_at": row["updated_at"] or 0,
            "guidance_segments": segments if isinstance(segments, list) else [],
            "finalized": finalized,
            "cycle_count": cycle_count,
        }

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
