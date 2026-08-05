"""Durable project-scoped state for native forensic programme analysis."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from .config import STORAGE_DIR


DB_PATH = Path(STORAGE_DIR) / "forensic.db"
MAX_WORKSPACE_BYTES = 75 * 1024 * 1024
UPSTREAM_SHA = "bb52fa0a5e41fc2040979b226911b192463701d5"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS forensic_programmes (
    file_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    uploaded_by TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    deleted_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_forensic_programme_content
    ON forensic_programmes(project_id, sha256) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_forensic_programmes_project
    ON forensic_programmes(project_id, deleted_at, created_at);

CREATE TABLE IF NOT EXISTS forensic_workspaces (
    workspace_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    created_by TEXT NOT NULL,
    name TEXT NOT NULL,
    programme_ids_json TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    source_revision TEXT NOT NULL,
    upstream_sha TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_forensic_workspaces_project
    ON forensic_workspaces(project_id, archived_at, updated_at);

CREATE TABLE IF NOT EXISTS forensic_module_runs (
    run_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    username TEXT NOT NULL,
    module_slug TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    source_revision TEXT NOT NULL,
    source_hashes_json TEXT NOT NULL,
    upstream_sha TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    result_json TEXT,
    error_code TEXT,
    traceback_id TEXT,
    attempt INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(workspace_id) REFERENCES forensic_workspaces(workspace_id)
);
CREATE INDEX IF NOT EXISTS idx_forensic_runs_queue
    ON forensic_module_runs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_forensic_runs_project
    ON forensic_module_runs(project_id, created_at);

CREATE TABLE IF NOT EXISTS forensic_artifacts (
    artifact_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES forensic_module_runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_forensic_artifacts_run
    ON forensic_artifacts(run_id, created_at);

CREATE TABLE IF NOT EXISTS forensic_workspace_state (
    workspace_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(workspace_id) REFERENCES forensic_workspaces(workspace_id)
);
CREATE INDEX IF NOT EXISTS idx_forensic_workspace_state_project
    ON forensic_workspace_state(project_id, updated_at);

CREATE TABLE IF NOT EXISTS forensic_workspace_sources (
    workspace_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    file_name TEXT NOT NULL,
    extension TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    capabilities_json TEXT NOT NULL,
    selected_scope_json TEXT NOT NULL,
    snapshot_path TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY(workspace_id, source_id),
    FOREIGN KEY(workspace_id) REFERENCES forensic_workspaces(workspace_id)
);
CREATE INDEX IF NOT EXISTS idx_forensic_workspace_sources_project
    ON forensic_workspace_sources(project_id, workspace_id, source_kind);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def source_revision(programmes: List[Dict[str, Any]], settings: Dict[str, Any]) -> str:
    payload = {
        "programmes": sorted(
            ({"file_id": p["file_id"], "sha256": p["sha256"]} for p in programmes),
            key=lambda item: item["file_id"],
        ),
        "settings": settings,
        "upstream_sha": UPSTREAM_SHA,
    }
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def default_workspace_state() -> Dict[str, Any]:
    """Canonical durable counterpart of the upstream Streamlit session state.

    The object is deliberately versioned and explicit.  Page-local React form
    values do not belong here; only decisions read by another module or by the
    report assembler are persisted in this contract.
    """
    return {
        "pipeline_version": "forensic-parity-v1",
        "baseline_programme_id": "",
        "current_programme_id": "",
        "contract_completion_milestone": "",
        "missing_inputs": [],
        "analysis_basis": {},
        "event_register": {},
        "apab": {
            "milestones": [], "paths": {}, "path_basis": {},
            "key_dates": {}, "date_basis": "late",
        },
        "umbrella": {"groups": {}, "proposed": [], "rounds": []},
        "sequence": {"mappings": {}, "confirmed": {}},
        "hierarchy": {"saved_configurations": {}},
        "explain": {"confirmed_drivers": {}},
        "iap": {"events": [], "last_run_id": ""},
        "tia": {"event_candidates": [], "candidate_source_ids": [],
                "candidate_audit_run_id": ""},
        "cab": {"groups": [], "extracted_activity_codes": [], "last_run_id": ""},
        "narratives": {},
        "report": {
            "title": "Preliminary Delay Analysis Report",
            "project": "", "prepared_by": "", "selected_sections": [],
            "include_charts": True,
        },
    }


def _deep_merge(current: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    merged = json.loads(_json(current))
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def workspace_source_revision(sources: List[Dict[str, Any]], state: Dict[str, Any] | None = None) -> str:
    """Hash only immutable source selections.

    Analyst decisions have their own optimistic ``state_version``.  Mixing
    those decisions into the source revision made every legitimate state edit
    look like a changed corpus and prevented the next module from running.
    ``state`` remains an optional argument for backwards-compatible callers.
    """
    payload = {
        "sources": sorted(
            ({"source_id": item["source_id"], "content_hash": item["content_hash"],
              "scope": item.get("selected_scope") or {}} for item in sources),
            key=lambda item: item["source_id"],
        ),
        "upstream_sha": UPSTREAM_SHA,
    }
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


class ForensicStore:
    _instance: Optional["ForensicStore"] = None
    _instance_lock = threading.Lock()

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @classmethod
    def instance(cls) -> "ForensicStore":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=20000")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _programme(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "file_id": row["file_id"], "name": row["file_name"],
            "size_bytes": int(row["size_bytes"]), "sha256": row["sha256"],
            "created_at": row["created_at"],
        }

    def list_programmes(self, project_id: str, *, include_path: bool = False) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM forensic_programmes WHERE project_id=? AND deleted_at IS NULL "
                "ORDER BY created_at,file_name", [project_id],
            ).fetchall()
        values = []
        for row in rows:
            item = self._programme(row)
            if include_path:
                item.update(file_path=row["file_path"], uploaded_by=row["uploaded_by"])
            values.append(item)
        return values

    def get_programme(self, project_id: str, file_id: str, *, include_path: bool = False) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM forensic_programmes WHERE project_id=? AND file_id=? "
                "AND deleted_at IS NULL", [project_id, file_id],
            ).fetchone()
        if not row:
            return None
        item = self._programme(row)
        if include_path:
            item.update(file_path=row["file_path"], uploaded_by=row["uploaded_by"])
        return item

    def find_content(self, project_id: str, sha256: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM forensic_programmes WHERE project_id=? AND sha256=? "
                "AND deleted_at IS NULL", [project_id, sha256],
            ).fetchone()
        return self._programme(row) if row else None

    def add_programme(self, *, project_id: str, username: str, file_name: str,
                      file_path: str, size_bytes: int, sha256: str) -> tuple[Dict[str, Any], bool]:
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM forensic_programmes WHERE project_id=? AND sha256=? "
                "AND deleted_at IS NULL", [project_id, sha256],
            ).fetchone()
            if existing:
                return self._programme(existing), True
            file_id = f"xer_{uuid.uuid4().hex[:20]}"
            now = _now()
            conn.execute(
                "INSERT INTO forensic_programmes VALUES (?,?,?,?,?,?,?,?,NULL)",
                [file_id, project_id, username, file_name, file_path,
                 int(size_bytes), sha256, now],
            )
            row = conn.execute("SELECT * FROM forensic_programmes WHERE file_id=?", [file_id]).fetchone()
        assert row is not None
        return self._programme(row), False

    def remove_programme(self, project_id: str, file_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM forensic_programmes WHERE project_id=? AND file_id=? "
                "AND deleted_at IS NULL", [project_id, file_id],
            ).fetchone()
            if not row:
                return None
            conn.execute("UPDATE forensic_programmes SET deleted_at=? WHERE file_id=?", [_now(), file_id])
        return dict(row)

    def create_workspace(self, *, project_id: str, username: str, name: str,
                         programme_ids: List[str], settings: Dict[str, Any]) -> Dict[str, Any]:
        programmes = self._resolve_programmes(project_id, programme_ids)
        if sum(p["size_bytes"] for p in programmes) > MAX_WORKSPACE_BYTES:
            raise ValueError("forensic_workspace_size_exceeded")
        workspace_id = f"fws_{uuid.uuid4().hex[:20]}"
        revision = source_revision(programmes, settings)
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO forensic_workspaces VALUES (?,?,?,?,?,?,?,?,?,?,NULL)",
                [workspace_id, project_id, username, name, _json(programme_ids),
                 _json(settings), revision, UPSTREAM_SHA, now, now],
            )
            row = conn.execute("SELECT * FROM forensic_workspaces WHERE workspace_id=?", [workspace_id]).fetchone()
            initial = default_workspace_state()
            initial["baseline_programme_id"] = programme_ids[0] if programme_ids else ""
            initial["current_programme_id"] = programme_ids[-1] if programme_ids else ""
            conn.execute(
                "INSERT INTO forensic_workspace_state VALUES (?,?,?,?,?,?)",
                [workspace_id, project_id, 1, _json(initial), now, now],
            )
        assert row is not None
        return self._workspace(row)

    def list_workspaces(self, project_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM forensic_workspaces WHERE project_id=? AND archived_at IS NULL "
                "ORDER BY updated_at DESC", [project_id],
            ).fetchall()
        return [self._workspace(r) for r in rows]

    def get_workspace(self, project_id: str, workspace_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM forensic_workspaces WHERE project_id=? AND workspace_id=? "
                "AND archived_at IS NULL", [project_id, workspace_id],
            ).fetchone()
        return self._workspace(row) if row else None

    def update_workspace(self, *, project_id: str, workspace_id: str,
                         name: Optional[str], programme_ids: Optional[List[str]],
                         settings: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        current = self.get_workspace(project_id, workspace_id)
        if not current:
            return None
        ids = programme_ids if programme_ids is not None else current["programme_ids"]
        merged_settings = settings if settings is not None else current["settings"]
        programmes = self._resolve_programmes(project_id, ids)
        if sum(p["size_bytes"] for p in programmes) > MAX_WORKSPACE_BYTES:
            raise ValueError("forensic_workspace_size_exceeded")
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE forensic_workspaces SET name=?,programme_ids_json=?,settings_json=?,"
                "source_revision=?,updated_at=? WHERE project_id=? AND workspace_id=?",
                [name or current["name"], _json(ids), _json(merged_settings),
                 source_revision(programmes, merged_settings), _now(), project_id, workspace_id],
            )
            row = conn.execute("SELECT * FROM forensic_workspaces WHERE workspace_id=?", [workspace_id]).fetchone()
        return self._workspace(row) if row else None

    def _resolve_programmes(self, project_id: str, ids: List[str]) -> List[Dict[str, Any]]:
        unique = list(dict.fromkeys(ids))
        values = [self.get_programme(project_id, file_id, include_path=True) for file_id in unique]
        if not unique or any(item is None for item in values):
            raise ValueError("forensic_programme_selection_invalid")
        return [item for item in values if item is not None]

    @staticmethod
    def _workspace(row: sqlite3.Row) -> Dict[str, Any]:
        item = dict(row)
        item["programme_ids"] = json.loads(item.pop("programme_ids_json"))
        item["settings"] = json.loads(item.pop("settings_json"))
        return item

    def get_workspace_state(self, project_id: str, workspace_id: str) -> Optional[Dict[str, Any]]:
        if not self.get_workspace(project_id, workspace_id):
            return None
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM forensic_workspace_state WHERE project_id=? AND workspace_id=?",
                [project_id, workspace_id],
            ).fetchone()
            if row is None:
                now = _now()
                state = default_workspace_state()
                workspace = self.get_workspace(project_id, workspace_id)
                ids = list((workspace or {}).get("programme_ids") or [])
                state["baseline_programme_id"] = ids[0] if ids else ""
                state["current_programme_id"] = ids[-1] if ids else ""
                conn.execute(
                    "INSERT INTO forensic_workspace_state VALUES (?,?,?,?,?,?)",
                    [workspace_id, project_id, 1, _json(state), now, now],
                )
                return {"workspace_id": workspace_id, "project_id": project_id,
                        "version": 1, "state": state, "created_at": now,
                        "updated_at": now}
        return {
            "workspace_id": row["workspace_id"], "project_id": row["project_id"],
            "version": int(row["version"]), "state": json.loads(row["state_json"]),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def update_workspace_state(self, *, project_id: str, workspace_id: str,
                               expected_version: int, patch: Dict[str, Any]) -> Dict[str, Any]:
        current = self.get_workspace_state(project_id, workspace_id)
        if current is None:
            raise ValueError("forensic_workspace_not_found")
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM forensic_workspace_state WHERE project_id=? AND workspace_id=?",
                [project_id, workspace_id],
            ).fetchone()
            if row is None:
                raise ValueError("forensic_workspace_state_not_found")
            if int(row["version"]) != int(expected_version):
                raise ValueError("forensic_workspace_state_version_conflict")
            state = _deep_merge(json.loads(row["state_json"]), patch)
            version = int(row["version"]) + 1
            now = _now()
            conn.execute(
                "UPDATE forensic_workspace_state SET version=?,state_json=?,updated_at=? "
                "WHERE project_id=? AND workspace_id=?",
                [version, _json(state), now, project_id, workspace_id],
            )
        return {"workspace_id": workspace_id, "project_id": project_id,
                "version": version, "state": state,
                "created_at": row["created_at"], "updated_at": now}

    @staticmethod
    def _source(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "source_id": row["source_id"], "source_kind": row["source_kind"],
            "file_name": row["file_name"], "extension": row["extension"],
            "size_bytes": int(row["size_bytes"]), "content_hash": row["content_hash"],
            "status": row["status"], "capabilities": json.loads(row["capabilities_json"]),
            "selected_scope": json.loads(row["selected_scope_json"]),
            "snapshot_path": row["snapshot_path"], "created_at": row["created_at"],
        }

    def list_workspace_sources(self, project_id: str, workspace_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM forensic_workspace_sources WHERE project_id=? AND workspace_id=? "
                "ORDER BY source_kind,file_name", [project_id, workspace_id],
            ).fetchall()
        return [self._source(row) for row in rows]

    def resolve_workspace_programmes(self, project_id: str,
                                     workspace_id: str) -> List[Dict[str, Any]]:
        """Return pinned XER snapshots, falling back to legacy programme rows."""
        selected = [item for item in self.list_workspace_sources(project_id, workspace_id)
                    if item["source_kind"] == "programme"]
        if selected:
            programmes = []
            for item in selected:
                path = Path(item.get("snapshot_path") or "")
                if not path.is_file():
                    raise ValueError("forensic_source_missing")
                programmes.append({
                    "file_id": item["source_id"], "name": item["file_name"],
                    "size_bytes": item["size_bytes"], "sha256": item["content_hash"],
                    "file_path": str(path),
                })
            return programmes
        workspace = self.get_workspace(project_id, workspace_id)
        if not workspace:
            raise ValueError("forensic_workspace_not_found")
        return self._resolve_programmes(project_id, workspace["programme_ids"])

    def replace_workspace_sources(self, *, project_id: str, workspace_id: str,
                                  expected_version: int,
                                  sources: List[Dict[str, Any]]) -> Dict[str, Any]:
        current = self.get_workspace_state(project_id, workspace_id)
        if current is None:
            raise ValueError("forensic_workspace_not_found")
        programme_ids = [item["source_id"] for item in sources
                         if item["source_kind"] == "programme"]
        if not programme_ids:
            raise ValueError("forensic_programme_selection_invalid")
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            state_row = conn.execute(
                "SELECT * FROM forensic_workspace_state WHERE project_id=? AND workspace_id=?",
                [project_id, workspace_id],
            ).fetchone()
            if state_row is None:
                raise ValueError("forensic_workspace_state_not_found")
            if int(state_row["version"]) != int(expected_version):
                raise ValueError("forensic_workspace_state_version_conflict")
            now = _now()
            conn.execute(
                "DELETE FROM forensic_workspace_sources WHERE project_id=? AND workspace_id=?",
                [project_id, workspace_id],
            )
            for item in sources:
                conn.execute(
                    "INSERT INTO forensic_workspace_sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [workspace_id, project_id, item["source_id"], item["source_kind"],
                     item["file_name"], item.get("extension", ""),
                     int(item.get("size_bytes") or 0), item["content_hash"],
                     item.get("status", "ready"), _json(item.get("capabilities") or []),
                     _json(item.get("selected_scope") or {}), item.get("snapshot_path"), now],
                )
            state = json.loads(state_row["state_json"])
            if state.get("baseline_programme_id") not in programme_ids:
                state["baseline_programme_id"] = programme_ids[0]
            if state.get("current_programme_id") not in programme_ids:
                state["current_programme_id"] = programme_ids[-1]
            version = int(state_row["version"]) + 1
            revision = workspace_source_revision(sources, state)
            conn.execute(
                "UPDATE forensic_workspace_state SET version=?,state_json=?,updated_at=? "
                "WHERE project_id=? AND workspace_id=?",
                [version, _json(state), now, project_id, workspace_id],
            )
            conn.execute(
                "UPDATE forensic_workspaces SET programme_ids_json=?,source_revision=?,updated_at=? "
                "WHERE project_id=? AND workspace_id=?",
                [_json(programme_ids), revision, now, project_id, workspace_id],
            )
        return {"workspace_id": workspace_id, "project_id": project_id,
                "version": version, "state": state,
                "source_revision": revision, "sources": sources,
                "updated_at": now}

    def enqueue_run(self, *, project_id: str, workspace_id: str, username: str,
                    module_slug: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self.get_workspace(project_id, workspace_id)
        if not workspace:
            raise ValueError("forensic_workspace_not_found")
        programmes = self.resolve_workspace_programmes(project_id, workspace_id)
        selected_sources = self.list_workspace_sources(project_id, workspace_id)
        state_record = self.get_workspace_state(project_id, workspace_id)
        current_revision = (
            workspace_source_revision(selected_sources)
            if selected_sources else source_revision(programmes, workspace["settings"])
        )
        if current_revision != workspace["source_revision"]:
            raise ValueError("forensic_workspace_sources_changed")
        parameters = dict(parameters)
        parameters["_state_version"] = int((state_record or {}).get("version") or 1)
        run_id = f"frun_{uuid.uuid4().hex[:20]}"
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO forensic_module_runs VALUES (?,?,?,?,?,?,?,?,?,'queued','queued',0,"
                "NULL,NULL,NULL,1,?,NULL,NULL,?)",
                [run_id, workspace_id, project_id, username, module_slug, _json(parameters),
                 current_revision, _json({p["file_id"]: p["sha256"] for p in programmes}),
                 UPSTREAM_SHA, now, now],
            )
            row = conn.execute("SELECT * FROM forensic_module_runs WHERE run_id=?", [run_id]).fetchone()
        assert row is not None
        return self._run(row)

    def list_runs(self, project_id: str, workspace_id: str = "") -> List[Dict[str, Any]]:
        where = "project_id=?" + (" AND workspace_id=?" if workspace_id else "")
        args = [project_id] + ([workspace_id] if workspace_id else [])
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM forensic_module_runs WHERE {where} ORDER BY created_at DESC", args,
            ).fetchall()
        return [self._run(r) for r in rows]

    def get_run(self, project_id: str, run_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM forensic_module_runs WHERE project_id=? AND run_id=?",
                [project_id, run_id],
            ).fetchone()
        return self._run(row) if row else None

    @staticmethod
    def _run(row: sqlite3.Row) -> Dict[str, Any]:
        item = dict(row)
        for field, output in (("parameters_json", "parameters"),
                              ("source_hashes_json", "source_hashes"),
                              ("result_json", "result")):
            raw = item.pop(field)
            item[output] = json.loads(raw) if raw else None
        return item

    def claim_next_run(self) -> Optional[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM forensic_module_runs WHERE status='queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if not row:
                return None
            now = _now()
            conn.execute(
                "UPDATE forensic_module_runs SET status='processing',stage='loading_programmes',"
                "progress=.05,started_at=COALESCE(started_at,?),updated_at=? WHERE run_id=?",
                [now, now, row["run_id"]],
            )
            row = conn.execute("SELECT * FROM forensic_module_runs WHERE run_id=?", [row["run_id"]]).fetchone()
        return self._run(row)

    def update_run(self, run_id: str, *, stage: str, progress: float) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE forensic_module_runs SET stage=?,progress=?,updated_at=? WHERE run_id=?",
                [stage, max(0.0, min(1.0, progress)), _now(), run_id],
            )

    def complete_run(self, run_id: str, result: Dict[str, Any]) -> None:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE forensic_module_runs SET status='ready',stage='ready',progress=1,"
                "result_json=?,error_code=NULL,traceback_id=NULL,completed_at=?,updated_at=? "
                "WHERE run_id=?", [_json(result), now, now, run_id],
            )

    def fail_run(self, run_id: str, *, error_code: str, traceback_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE forensic_module_runs SET status='failed',stage='failed',error_code=?,"
                "traceback_id=?,updated_at=? WHERE run_id=?",
                [error_code, traceback_id, _now(), run_id],
            )

    def recover_runs(self) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE forensic_module_runs SET status='queued',stage='queued',progress=0,"
                "updated_at=? WHERE status='processing'", [_now()],
            )
        return cur.rowcount

    def retry_run(self, project_id: str, run_id: str) -> Optional[Dict[str, Any]]:
        current = self.get_run(project_id, run_id)
        if not current or current["status"] != "failed":
            return None
        workspace = self.get_workspace(project_id, current["workspace_id"])
        if not workspace or workspace["source_revision"] != current["source_revision"]:
            return None
        state = self.get_workspace_state(project_id, current["workspace_id"])
        expected_state_version = int((current.get("parameters") or {}).get("_state_version") or 1)
        if not state or int(state["version"]) != expected_state_version:
            return None
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE forensic_module_runs SET status='queued',stage='queued',progress=0,"
                "error_code=NULL,traceback_id=NULL,attempt=attempt+1,updated_at=? WHERE run_id=?",
                [_now(), run_id],
            )
            row = conn.execute("SELECT * FROM forensic_module_runs WHERE run_id=?", [run_id]).fetchone()
        return self._run(row) if row else None

    def add_artifact(self, *, run_id: str, project_id: str, kind: str, name: str,
                     mime_type: str, file_path: str) -> Dict[str, Any]:
        path = Path(file_path)
        raw = path.read_bytes()
        artifact_id = f"fart_{uuid.uuid4().hex[:20]}"
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO forensic_artifacts VALUES (?,?,?,?,?,?,?,?,?,?)",
                [artifact_id, run_id, project_id, kind, name, mime_type, str(path),
                 len(raw), hashlib.sha256(raw).hexdigest(), now],
            )
            row = conn.execute("SELECT * FROM forensic_artifacts WHERE artifact_id=?", [artifact_id]).fetchone()
        assert row is not None
        return self._artifact(row)

    def list_artifacts(self, project_id: str, run_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM forensic_artifacts WHERE project_id=? AND run_id=? ORDER BY created_at",
                [project_id, run_id],
            ).fetchall()
        return [self._artifact(r) for r in rows]

    def get_artifact(self, project_id: str, artifact_id: str, *, include_path: bool = False) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM forensic_artifacts WHERE project_id=? AND artifact_id=?",
                [project_id, artifact_id],
            ).fetchone()
        if not row:
            return None
        item = self._artifact(row)
        if include_path:
            item["file_path"] = row["file_path"]
        return item

    @staticmethod
    def _artifact(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "artifact_id": row["artifact_id"], "run_id": row["run_id"],
            "kind": row["kind"], "name": row["name"], "mime_type": row["mime_type"],
            "size_bytes": int(row["size_bytes"]), "sha256": row["sha256"],
            "created_at": row["created_at"],
            "download_url": f"/api/forensic/artifacts/{row['artifact_id']}/download",
        }


def get_forensic_store() -> ForensicStore:
    return ForensicStore.instance()


__all__ = ["ForensicStore", "MAX_WORKSPACE_BYTES", "UPSTREAM_SHA",
           "default_workspace_state", "get_forensic_store", "source_revision",
           "workspace_source_revision"]
