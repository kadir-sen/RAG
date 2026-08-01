"""SQLite-backed projects and project memberships.

Projects are the security boundary for every document, conversation, report,
query run and derived index record.  This store deliberately keeps membership
checks in one place so route handlers cannot improvise their own visibility
rules.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from .config import STORAGE_DIR


PROJECTS_DB = Path(STORAGE_DIR) / "projects.db"
PROJECT_ROLES = ("owner", "editor", "viewer")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    project_id          TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    slug                TEXT NOT NULL,
    embedding_profile   TEXT NOT NULL DEFAULT 'local-bge-v1',
    created_by          TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    archived_at         TEXT
);
CREATE TABLE IF NOT EXISTS project_members (
    project_id  TEXT NOT NULL,
    username    TEXT NOT NULL,
    role        TEXT NOT NULL CHECK(role IN ('owner','editor','viewer')),
    created_at  TEXT NOT NULL,
    PRIMARY KEY(project_id, username),
    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_project_members_user
    ON project_members(username, project_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return slug[:64] or "project"


class ProjectStore:
    _instance: Optional["ProjectStore"] = None
    _instance_lock = threading.Lock()

    def __init__(self, db_path: Path = PROJECTS_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @classmethod
    def instance(cls) -> "ProjectStore":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _row(row: sqlite3.Row, role: str = "") -> Dict[str, Any]:
        return {
            "project_id": row["project_id"],
            "name": row["name"],
            "slug": row["slug"],
            "embedding_profile": row["embedding_profile"],
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "archived_at": row["archived_at"],
            "role": role,
        }

    def create_project(
        self,
        name: str,
        owner: str,
        *,
        embedding_profile: str = "local-bge-v1",
    ) -> Dict[str, Any]:
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("project name is required")
        if embedding_profile not in ("local-bge-v1", "gemini-embedding-2"):
            raise ValueError("unsupported embedding profile")
        project_id = uuid.uuid4().hex[:16]
        now = _now()
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO projects VALUES (?,?,?,?,?,?,?,NULL)",
                [project_id, clean_name[:160], _slug(clean_name), embedding_profile,
                 owner, now, now],
            )
            conn.execute(
                "INSERT INTO project_members VALUES (?,?,?,?)",
                [project_id, owner, "owner", now],
            )
        return self.get_for_user(project_id, owner) or {}

    def list_for_user(self, username: str, *, include_archived: bool = False) -> List[Dict[str, Any]]:
        sql = (
            "SELECT p.*, m.role FROM projects p JOIN project_members m "
            "ON m.project_id=p.project_id WHERE m.username=?"
        )
        params: List[Any] = [username]
        if not include_archived:
            sql += " AND p.archived_at IS NULL"
        sql += " ORDER BY p.updated_at DESC, p.name"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row(r, r["role"]) for r in rows]

    def list_all(self, *, include_archived: bool = False) -> List[Dict[str, Any]]:
        sql = "SELECT p.*, 'admin' AS role FROM projects p"
        if not include_archived:
            sql += " WHERE p.archived_at IS NULL"
        sql += " ORDER BY p.updated_at DESC, p.name"
        with self._connect() as conn:
            rows = conn.execute(sql).fetchall()
        return [self._row(r, "admin") for r in rows]

    def get_for_user(self, project_id: str, username: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT p.*, m.role FROM projects p JOIN project_members m "
                "ON m.project_id=p.project_id WHERE p.project_id=? AND m.username=?",
                [project_id, username],
            ).fetchone()
        return self._row(row, row["role"]) if row else None

    def get(self, project_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE project_id=?", [project_id]).fetchone()
        return self._row(row) if row else None

    def add_member(self, project_id: str, username: str, role: str) -> None:
        if role not in PROJECT_ROLES:
            raise ValueError("invalid project role")
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO project_members VALUES (?,?,?,?) "
                "ON CONFLICT(project_id,username) DO UPDATE SET role=excluded.role",
                [project_id, username, role, _now()],
            )

    def archive(self, project_id: str) -> bool:
        now = _now()
        with self._write_lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE projects SET archived_at=?, updated_at=? "
                "WHERE project_id=? AND archived_at IS NULL",
                [now, now, project_id],
            )
        return cur.rowcount > 0

    def rename(self, project_id: str, name: str) -> Optional[Dict[str, Any]]:
        clean = (name or "").strip()
        if not clean:
            raise ValueError("project name is required")
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "UPDATE projects SET name=?, slug=?, updated_at=? WHERE project_id=?",
                [clean[:160], _slug(clean), _now(), project_id],
            )
        return self.get(project_id)


def get_project_store() -> ProjectStore:
    return ProjectStore.instance()


__all__ = ["PROJECT_ROLES", "ProjectStore", "get_project_store"]
