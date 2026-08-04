"""Durable programme files and one-time Streamlit launch sessions."""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from .billing_store import DB_PATH


MAX_ANALYSIS_BYTES = 75 * 1024 * 1024
TICKET_TTL_SECONDS = 60
SESSION_TTL_SECONDS = 12 * 60 * 60

_SCHEMA = """
CREATE TABLE IF NOT EXISTS toolkit_programmes (
    file_id       TEXT NOT NULL,
    project_id    TEXT NOT NULL,
    uploaded_by   TEXT NOT NULL,
    file_name     TEXT NOT NULL,
    file_path     TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    sha256        TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    deleted_at    TEXT,
    PRIMARY KEY(project_id, file_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_toolkit_programme_content
    ON toolkit_programmes(project_id, sha256) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_toolkit_programmes_project
    ON toolkit_programmes(project_id, deleted_at, created_at);

CREATE TABLE IF NOT EXISTS toolkit_sessions (
    ticket_hash        TEXT PRIMARY KEY,
    username           TEXT NOT NULL,
    project_id         TEXT NOT NULL,
    project_role       TEXT NOT NULL,
    created_at         INTEGER NOT NULL,
    expires_at         INTEGER NOT NULL,
    consumed_at        INTEGER,
    session_hash       TEXT UNIQUE,
    session_expires_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_toolkit_sessions_session
    ON toolkit_sessions(session_hash, session_expires_at);
"""


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ToolkitStore:
    _instance: Optional["ToolkitStore"] = None
    _instance_lock = threading.Lock()

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @classmethod
    def instance(cls) -> "ToolkitStore":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 20000")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _public(row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
        record = dict(row)
        return {
            "file_id": record["file_id"],
            "name": record["file_name"],
            "size_bytes": int(record["size_bytes"]),
            "sha256": record["sha256"],
            "created_at": record["created_at"],
        }

    def list_programmes(self, project_id: str, *, include_path: bool = False) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM toolkit_programmes WHERE project_id=? AND deleted_at IS NULL "
                "ORDER BY created_at,file_name", [project_id],
            ).fetchall()
        result = []
        for row in rows:
            item = self._public(row)
            if include_path:
                item["file_path"] = row["file_path"]
                item["uploaded_by"] = row["uploaded_by"]
            result.append(item)
        return result

    def total_bytes(self, project_id: str) -> int:
        with self._connect() as conn:
            return int(conn.execute(
                "SELECT COALESCE(SUM(size_bytes),0) FROM toolkit_programmes "
                "WHERE project_id=? AND deleted_at IS NULL", [project_id],
            ).fetchone()[0])

    def get_programme(
        self, project_id: str, file_id: str, *, include_path: bool = False,
    ) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM toolkit_programmes WHERE project_id=? AND file_id=? "
                "AND deleted_at IS NULL", [project_id, file_id],
            ).fetchone()
        if not row:
            return None
        item = self._public(row)
        if include_path:
            item["file_path"] = row["file_path"]
            item["uploaded_by"] = row["uploaded_by"]
        return item

    def find_content(self, project_id: str, sha256: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM toolkit_programmes WHERE project_id=? AND sha256=? "
                "AND deleted_at IS NULL", [project_id, sha256],
            ).fetchone()
        return self._public(row) if row else None

    def add_programme(
        self, *, project_id: str, username: str, file_name: str,
        file_path: str, size_bytes: int, sha256: str,
    ) -> Dict[str, Any]:
        file_id = f"xer_{sha256[:24]}"
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            prior = conn.execute(
                "SELECT * FROM toolkit_programmes WHERE project_id=? AND sha256=? "
                "AND deleted_at IS NULL", [project_id, sha256],
            ).fetchone()
            if prior:
                return self._public(prior)
            total = int(conn.execute(
                "SELECT COALESCE(SUM(size_bytes),0) FROM toolkit_programmes "
                "WHERE project_id=? AND deleted_at IS NULL", [project_id],
            ).fetchone()[0])
            if total + int(size_bytes) > MAX_ANALYSIS_BYTES:
                raise ValueError("toolkit_analysis_size_exceeded")
            now = _iso_now()
            conn.execute(
                "INSERT INTO toolkit_programmes "
                "(file_id,project_id,uploaded_by,file_name,file_path,size_bytes,sha256,created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                [file_id, project_id, username, file_name, file_path,
                 int(size_bytes), sha256, now],
            )
            row = conn.execute(
                "SELECT * FROM toolkit_programmes WHERE project_id=? AND file_id=?",
                [project_id, file_id],
            ).fetchone()
            assert row is not None
            return self._public(row)

    def remove_programme(self, project_id: str, file_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM toolkit_programmes WHERE project_id=? AND file_id=? "
                "AND deleted_at IS NULL", [project_id, file_id],
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE toolkit_programmes SET deleted_at=? WHERE project_id=? AND file_id=?",
                [_iso_now(), project_id, file_id],
            )
            record = dict(row)
            return record

    def create_ticket(self, *, username: str, project_id: str, project_role: str) -> str:
        ticket = secrets.token_urlsafe(32)
        now = int(time.time())
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "DELETE FROM toolkit_sessions WHERE "
                "(consumed_at IS NULL AND expires_at<?) OR "
                "(consumed_at IS NOT NULL AND session_expires_at<?)", [now, now],
            )
            conn.execute(
                "INSERT INTO toolkit_sessions "
                "(ticket_hash,username,project_id,project_role,created_at,expires_at) "
                "VALUES (?,?,?,?,?,?)",
                [_sha(ticket), username, project_id, project_role, now,
                 now + TICKET_TTL_SECONDS],
            )
        return ticket

    def consume_ticket(self, ticket: str) -> Optional[Dict[str, Any]]:
        now = int(time.time())
        session_token = secrets.token_urlsafe(40)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM toolkit_sessions WHERE ticket_hash=?",
                [_sha(ticket)],
            ).fetchone()
            if not row or row["consumed_at"] is not None or int(row["expires_at"]) < now:
                return None
            session_expires = now + SESSION_TTL_SECONDS
            conn.execute(
                "UPDATE toolkit_sessions SET consumed_at=?,session_hash=?,session_expires_at=? "
                "WHERE ticket_hash=? AND consumed_at IS NULL",
                [now, _sha(session_token), session_expires, _sha(ticket)],
            )
            return {
                "session_token": session_token,
                "session_expires_at": session_expires,
                "username": row["username"],
                "project_id": row["project_id"],
                "project_role": row["project_role"],
            }

    def validate_session(self, session_token: str) -> Optional[Dict[str, Any]]:
        now = int(time.time())
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM toolkit_sessions WHERE session_hash=? AND consumed_at IS NOT NULL "
                "AND session_expires_at>=?", [_sha(session_token), now],
            ).fetchone()
        return dict(row) if row else None


def get_toolkit_store() -> ToolkitStore:
    return ToolkitStore.instance()


__all__ = [
    "MAX_ANALYSIS_BYTES", "SESSION_TTL_SECONDS", "TICKET_TTL_SECONDS",
    "ToolkitStore", "get_toolkit_store",
]
