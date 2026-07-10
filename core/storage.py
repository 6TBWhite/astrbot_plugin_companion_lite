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
            CREATE TABLE IF NOT EXISTS session_arc (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                started_at REAL NOT NULL,
                last_activity_at REAL NOT NULL,
                ended_at REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'open',
                start_snapshot TEXT NOT NULL DEFAULT '{}',
                end_snapshot TEXT NOT NULL DEFAULT '{}',
                peak_boundary_pressure REAL NOT NULL DEFAULT 0,
                peak_negative_trend REAL NOT NULL DEFAULT 0,
                peak_positive_trend REAL NOT NULL DEFAULT 0,
                min_energy REAL NOT NULL DEFAULT 90,
                message_count INTEGER NOT NULL DEFAULT 0,
                turning_points TEXT NOT NULL DEFAULT '[]',
                outcome TEXT NOT NULL DEFAULT 'ongoing',
                summary TEXT NOT NULL DEFAULT '',
                reflection_count INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_session_arc_user_status
                ON session_arc(user_id, status, last_activity_at);
            CREATE TABLE IF NOT EXISTS interaction_profile_evidence (
                user_id TEXT NOT NULL,
                profile_key TEXT NOT NULL,
                profile_value TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'observed',
                positive_evidence INTEGER NOT NULL DEFAULT 0,
                negative_evidence INTEGER NOT NULL DEFAULT 0,
                confidence REAL NOT NULL DEFAULT 0,
                first_observed_at REAL NOT NULL,
                last_observed_at REAL NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (user_id, profile_key)
            );
        """)
        self._conn.commit()

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
            "SELECT id, role, content, timestamp FROM message_buffer WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        rows = cur.fetchall()
        return [
            {"id": r["id"], "role": r["role"], "content": r["content"], "timestamp": r["timestamp"]}
            for r in reversed(rows)
        ]

    def get_messages_for_reflection(self, user_id: str, limit: int = 40) -> list[dict[str, Any]]:
        """Return the oldest pending messages so snapshot cleanup never skips history."""
        cur = self._conn.cursor()
        cur.execute(
            "SELECT id, role, content, timestamp FROM message_buffer "
            "WHERE user_id = ? ORDER BY id ASC LIMIT ?",
            (user_id, limit),
        )
        return [dict(row) for row in cur.fetchall()]

    def delete_messages_through(self, user_id: str, max_message_id: int) -> None:
        """Delete only messages included in a completed reflection snapshot."""
        cur = self._conn.cursor()
        cur.execute(
            "DELETE FROM message_buffer WHERE user_id = ? AND id <= ?",
            (user_id, max_message_id),
        )
        self._conn.commit()

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

    def get_latest_user_message_id(self, user_id: str) -> int:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT id FROM message_buffer WHERE user_id = ? AND role = 'user' ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        row = cur.fetchone()
        return int(row["id"]) if row else 0

    def count_completed_rounds(self, user_id: str) -> int:
        """Count user-to-assistant exchanges without treating raw message count as rounds."""
        cur = self._conn.cursor()
        cur.execute(
            "SELECT role FROM message_buffer WHERE user_id = ? ORDER BY id ASC",
            (user_id,),
        )
        waiting_for_assistant = False
        completed = 0
        for row in cur.fetchall():
            role = row["role"]
            if role == "user":
                waiting_for_assistant = True
            elif role == "assistant" and waiting_for_assistant:
                completed += 1
                waiting_for_assistant = False
        return completed

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

    def create_session_arc(self, user_id: str, snapshot: dict[str, Any], now: float) -> dict[str, Any]:
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO session_arc (user_id, started_at, last_activity_at, start_snapshot, "
            "peak_boundary_pressure, peak_negative_trend, peak_positive_trend, min_energy, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                now,
                now,
                json.dumps(snapshot, ensure_ascii=False),
                float(snapshot.get("boundary_pressure", 0.0)),
                float(snapshot.get("negative_trend", 0.0)),
                float(snapshot.get("positive_trend", 0.0)),
                float(snapshot.get("energy", 90.0)),
                now,
            ),
        )
        self._conn.commit()
        return self.get_session_arc(int(cur.lastrowid)) or {}

    def get_session_arc(self, session_id: int) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM session_arc WHERE id = ?", (session_id,))
        row = cur.fetchone()
        return self._session_row_to_dict(row) if row else None

    def get_open_session_arc(self, user_id: str) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT * FROM session_arc WHERE user_id = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        row = cur.fetchone()
        return self._session_row_to_dict(row) if row else None

    def update_session_arc(self, session_id: int, arc: dict[str, Any]) -> None:
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE session_arc SET last_activity_at=?, ended_at=?, status=?, end_snapshot=?, "
            "peak_boundary_pressure=?, peak_negative_trend=?, peak_positive_trend=?, min_energy=?, "
            "message_count=?, turning_points=?, outcome=?, summary=?, reflection_count=?, updated_at=? WHERE id=?",
            (
                float(arc.get("last_activity_at", time.time())),
                float(arc.get("ended_at", 0.0)),
                str(arc.get("status", "open")),
                json.dumps(arc.get("end_snapshot", {}), ensure_ascii=False),
                float(arc.get("peak_boundary_pressure", 0.0)),
                float(arc.get("peak_negative_trend", 0.0)),
                float(arc.get("peak_positive_trend", 0.0)),
                float(arc.get("min_energy", 90.0)),
                int(arc.get("message_count", 0)),
                json.dumps(arc.get("turning_points", []), ensure_ascii=False),
                str(arc.get("outcome", "ongoing")),
                str(arc.get("summary", ""))[:240],
                int(arc.get("reflection_count", 0)),
                time.time(),
                session_id,
            ),
        )
        self._conn.commit()

    def get_recent_session_arcs(self, user_id: str, limit: int = 7, closed_only: bool = False) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        status_filter = "AND status = 'closed'" if closed_only else ""
        cur.execute(
            f"SELECT * FROM session_arc WHERE user_id = ? {status_filter} ORDER BY id DESC LIMIT ?",
            (user_id, max(1, limit)),
        )
        return [self._session_row_to_dict(row) for row in cur.fetchall()]

    def clear_session_arcs(self, user_id: str) -> None:
        self._conn.execute("DELETE FROM session_arc WHERE user_id = ?", (user_id,))
        self._conn.commit()

    def upsert_profile_evidence(self, user_id: str, evidence: dict[str, Any]) -> None:
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO interaction_profile_evidence "
            "(user_id, profile_key, profile_value, source, positive_evidence, negative_evidence, confidence, "
            "first_observed_at, last_observed_at, active) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, profile_key) DO UPDATE SET profile_value=excluded.profile_value, "
            "source=excluded.source, positive_evidence=excluded.positive_evidence, "
            "negative_evidence=excluded.negative_evidence, confidence=excluded.confidence, "
            "last_observed_at=excluded.last_observed_at, active=excluded.active",
            (
                user_id,
                str(evidence.get("key", "")),
                str(evidence.get("value", "")),
                str(evidence.get("source", "observed")),
                int(evidence.get("positive_evidence", 0)),
                int(evidence.get("negative_evidence", 0)),
                float(evidence.get("confidence", 0.0)),
                float(evidence.get("first_observed_at", now)),
                float(evidence.get("last_observed_at", now)),
                int(bool(evidence.get("active", True))),
            ),
        )
        self._conn.commit()

    def get_profile_evidence(self, user_id: str) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT * FROM interaction_profile_evidence WHERE user_id = ? ORDER BY profile_key",
            (user_id,),
        )
        return [dict(row) | {"active": bool(row["active"])} for row in cur.fetchall()]

    def clear_profile_evidence(self, user_id: str) -> None:
        self._conn.execute("DELETE FROM interaction_profile_evidence WHERE user_id = ?", (user_id,))
        self._conn.commit()

    @staticmethod
    def _session_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        for field, default in (("start_snapshot", {}), ("end_snapshot", {}), ("turning_points", [])):
            try:
                result[field] = json.loads(result.get(field) or json.dumps(default))
            except (json.JSONDecodeError, TypeError):
                result[field] = default
        return result

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
