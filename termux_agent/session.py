"""Small SQLite-backed session store with no external dependencies."""

from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path
from typing import Iterable


class SessionStore:
    def __init__(self, database: Path):
        self.database = database.expanduser()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
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

    def get(self, session_id: str) -> dict | None:
        with self._connect() as db:
            session = db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if session is None:
                return None
            messages = db.execute(
                "SELECT role, content, created_at FROM messages WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        return {"session": dict(session), "messages": [dict(row) for row in messages]}

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
