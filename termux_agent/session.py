"""SQLite-backed sessions, governance audit events, and evidence records."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Iterable


class SessionStore:
    def __init__(self, database: Path):
        self.database = database.expanduser()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON messages(session_id, id);
                CREATE TABLE IF NOT EXISTS governance_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
                    event TEXT NOT NULL,
                    from_state TEXT,
                    to_state TEXT,
                    reason TEXT NOT NULL,
                    evidence_kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_governance_session
                    ON governance_events(session_id, id);
                CREATE TABLE IF NOT EXISTS evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL CHECK(kind IN ('OBSERVED', 'INFERRED', 'UNKNOWN')),
                    source TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_evidence_session
                    ON evidence(session_id, id);
                CREATE TABLE IF NOT EXISTS governance_snapshots (
                    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
                    state TEXT NOT NULL,
                    consecutive_executions INTEGER NOT NULL,
                    last_failure_digest TEXT,
                    last_failure_count INTEGER NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )

    def create(self, title: str) -> str:
        session_id = uuid.uuid4().hex
        now = time.time()
        with self._connect() as db:
            db.execute(
                "INSERT INTO sessions(id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (session_id, title.strip() or "Untitled session", now, now),
            )
        return session_id

    def add_message(self, session_id: str, role: str, content: str) -> None:
        if role not in {"system", "user", "assistant", "tool"}:
            raise ValueError("role must be system, user, assistant, or tool")
        now = time.time()
        with self._connect() as db:
            db.execute(
                "INSERT INTO messages(session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (session_id, role, content, now),
            )
            db.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))

    def save_governance_snapshot(self, session_id: str | None, snapshot: dict[str, Any]) -> None:
        if not session_id:
            return
        now = time.time()
        with self._connect() as db:
            db.execute(
                """INSERT INTO governance_snapshots
                   (session_id, state, consecutive_executions, last_failure_digest, last_failure_count, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                     state = excluded.state,
                     consecutive_executions = excluded.consecutive_executions,
                     last_failure_digest = excluded.last_failure_digest,
                     last_failure_count = excluded.last_failure_count,
                     updated_at = excluded.updated_at""",
                (
                    session_id,
                    str(snapshot.get("state", "ANALYZING")),
                    int(snapshot.get("consecutive_executions", 0)),
                    snapshot.get("last_failure_digest"),
                    int(snapshot.get("last_failure_count", 0)),
                    now,
                ),
            )
            db.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))

    def get_governance_snapshot(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT state, consecutive_executions, last_failure_digest, last_failure_count, updated_at "
                "FROM governance_snapshots WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    def add_governance_event(self, session_id: str | None, event: dict[str, Any]) -> None:
        now = time.time()
        with self._connect() as db:
            db.execute(
                """INSERT INTO governance_events
                   (session_id, event, from_state, to_state, reason, evidence_kind, payload_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    str(event.get("event", "unknown")),
                    event.get("from_state"),
                    event.get("to_state"),
                    str(event.get("reason", ""))[:1000],
                    str(event.get("evidence_kind", "UNKNOWN")),
                    json.dumps(event.get("payload", {}), ensure_ascii=False, sort_keys=True),
                    now,
                ),
            )
            if session_id:
                db.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))

    def add_evidence(
        self,
        session_id: str | None,
        kind: str,
        source: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        kind = kind.upper()
        if kind not in {"OBSERVED", "INFERRED", "UNKNOWN"}:
            raise ValueError("evidence kind must be OBSERVED, INFERRED, or UNKNOWN")
        now = time.time()
        with self._connect() as db:
            cursor = db.execute(
                """INSERT INTO evidence
                   (session_id, kind, source, content, metadata_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session_id, kind, source[:200], content[:10_000], json.dumps(metadata or {}, ensure_ascii=False), now),
            )
            if session_id:
                db.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
            return int(cursor.lastrowid)

    def get(self, session_id: str) -> dict | None:
        with self._connect() as db:
            session = db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if session is None:
                return None
            messages = db.execute(
                "SELECT role, content, created_at FROM messages WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
            events = db.execute(
                "SELECT event, from_state, to_state, reason, evidence_kind, payload_json, created_at "
                "FROM governance_events WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
            evidence = db.execute(
                "SELECT kind, source, content, metadata_json, created_at FROM evidence WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
            snapshot = db.execute(
                "SELECT state, consecutive_executions, last_failure_digest, last_failure_count, updated_at "
                "FROM governance_snapshots WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return {
            "session": dict(session),
            "governance": dict(snapshot) if snapshot else None,
            "messages": [dict(row) for row in messages],
            "governance_events": [dict(row) for row in events],
            "evidence": [dict(row) for row in evidence],
        }

    def list(self, limit: int = 20) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def export_messages(self, session_id: str) -> Iterable[tuple[str, str]]:
        record = self.get(session_id)
        if record is None:
            raise KeyError(session_id)
        return ((message["role"], message["content"]) for message in record["messages"])
