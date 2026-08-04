"""Authoritative per-query run, step and LLM-call audit store."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from .config import STORAGE_DIR
from .types import LLMUsage


RUNS_DB = Path(STORAGE_DIR) / "query_runs.db"
current_run_id_var: ContextVar[str] = ContextVar("query_run_id", default="")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS query_runs (
    run_id TEXT PRIMARY KEY, project_id TEXT, username TEXT, module TEXT,
    query TEXT, route TEXT, status TEXT, created_at TEXT, completed_at TEXT,
    latency_ms REAL, source_count INTEGER, footnote_count INTEGER,
    verification TEXT, metrics_complete INTEGER NOT NULL DEFAULT 1,
    prompt_version TEXT, model_policy TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS query_steps (
    run_id TEXT NOT NULL, seq INTEGER NOT NULL, kind TEXT, label TEXT,
    detail TEXT, status TEXT, started_at TEXT, latency_ms REAL,
    PRIMARY KEY(run_id, seq)
);
CREATE TABLE IF NOT EXISTS llm_calls (
    call_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, provider TEXT, model TEXT,
    prompt_tokens INTEGER, completion_tokens INTEGER, reasoning_tokens INTEGER,
    cached_tokens INTEGER, cost_usd REAL, latency_ms REAL, cache_hit INTEGER,
    created_at TEXT, task_type TEXT, finish_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_query_runs_project ON query_runs(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_query_runs_user ON query_runs(username, created_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunStore:
    _instance: Optional["RunStore"] = None
    _instance_lock = threading.Lock()

    def __init__(self, db_path: Path = RUNS_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._started = {}
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            llm_columns = {row[1] for row in conn.execute("PRAGMA table_info(llm_calls)")}
            if "task_type" not in llm_columns:
                conn.execute("ALTER TABLE llm_calls ADD COLUMN task_type TEXT")
            if "finish_reason" not in llm_columns:
                conn.execute("ALTER TABLE llm_calls ADD COLUMN finish_reason TEXT")

    @classmethod
    def instance(cls) -> "RunStore":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def start(self, *, run_id: str = "", project_id: str, username: str,
              module: str, query: str, prompt_version: str = "",
              model_policy: str = "quality-demo-v1") -> str:
        rid = run_id or uuid.uuid4().hex[:20]
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO query_runs "
                "(run_id,project_id,username,module,query,route,status,created_at,"
                "metrics_complete,prompt_version,model_policy) VALUES (?,?,?,?,?,'','running',?,?,?,?)",
                [rid, project_id, username, module, (query or "")[:8000], now, 1,
                 prompt_version, model_policy],
            )
            self._started[rid] = time.monotonic()
        current_run_id_var.set(rid)
        return rid

    def add_step(self, run_id: str, kind: str, label: str, detail: str = "",
                 status: str = "ok", latency_ms: float = 0.0) -> None:
        if not run_id:
            return
        with self._lock, self._connect() as conn:
            seq = conn.execute(
                "SELECT COALESCE(MAX(seq),-1)+1 FROM query_steps WHERE run_id=?", [run_id]
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO query_steps VALUES (?,?,?,?,?,?,?,?)",
                [run_id, int(seq), kind, label[:500], detail[:2000], status, _now(), latency_ms],
            )

    def record_llm(self, usage: LLMUsage, run_id: str = "") -> None:
        rid = run_id or current_run_id_var.get()
        if not rid:
            return
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO llm_calls "
                "(call_id,run_id,provider,model,prompt_tokens,completion_tokens,"
                "reasoning_tokens,cached_tokens,cost_usd,latency_ms,cache_hit,created_at,"
                "task_type,finish_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [uuid.uuid4().hex[:24], rid, usage.provider, usage.model,
                 int(usage.prompt_tokens), int(usage.completion_tokens),
                 int(getattr(usage, "reasoning_tokens", 0) or 0),
                 int(getattr(usage, "cached_tokens", 0) or 0),
                 float(usage.cost_estimate), float(usage.latency_ms),
                 1 if usage.cache_hit else 0, _now(),
                 getattr(usage, "task_type", ""), getattr(usage, "finish_reason", "")],
            )

    def finish(self, run_id: str, *, status: str = "completed", route: str = "",
               source_count: int = 0, footnote_count: int = 0,
               verification: str = "", error: str = "") -> None:
        started = self._started.pop(run_id, None)
        latency = (time.monotonic() - started) * 1000 if started is not None else None
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE query_runs SET status=?, route=?, completed_at=?, latency_ms=?, "
                "source_count=?, footnote_count=?, verification=?, error=? WHERE run_id=?",
                [status, route, _now(), latency, int(source_count), int(footnote_count),
                 verification, error[:2000], run_id],
            )

    def recent(self, *, project_id: str = "", username: str = "", admin: bool = False,
               limit: int = 200) -> List[Dict[str, Any]]:
        where, params = [], []
        if project_id:
            where.append("r.project_id=?"); params.append(project_id)
        if username and not admin:
            where.append("r.username=?"); params.append(username)
        clause = " WHERE " + " AND ".join(where) if where else ""
        sql = (
            "SELECT r.*, "
            "(SELECT COUNT(*) FROM query_steps s WHERE s.run_id=r.run_id) AS total_steps, "
            "(SELECT COUNT(*) FROM query_steps s WHERE s.run_id=r.run_id AND s.status='ok') AS successful_steps, "
            "(SELECT COUNT(*) FROM query_steps s WHERE s.run_id=r.run_id AND s.status='error') AS failed_steps, "
            "(SELECT COUNT(*) FROM query_steps s WHERE s.run_id=r.run_id AND s.status='fallback') AS fallback_steps, "
            "(SELECT COUNT(*) FROM llm_calls l WHERE l.run_id=r.run_id) AS llm_call_count, "
            "(SELECT SUM(prompt_tokens) FROM llm_calls l WHERE l.run_id=r.run_id) AS input_tokens, "
            "(SELECT SUM(completion_tokens) FROM llm_calls l WHERE l.run_id=r.run_id) AS output_tokens, "
            "(SELECT SUM(reasoning_tokens) FROM llm_calls l WHERE l.run_id=r.run_id) AS reasoning_tokens, "
            "(SELECT SUM(cached_tokens) FROM llm_calls l WHERE l.run_id=r.run_id) AS cached_tokens, "
            "(SELECT SUM(cost_usd) FROM llm_calls l WHERE l.run_id=r.run_id) AS cost_usd "
            "FROM query_runs r" + clause + " ORDER BY r.created_at DESC LIMIT ?"
        )
        params.append(max(1, min(1000, limit)))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            if not item.get("metrics_complete"):
                for key in ("total_steps", "successful_steps", "failed_steps", "fallback_steps",
                            "llm_call_count", "input_tokens", "output_tokens", "reasoning_tokens",
                            "cached_tokens", "cost_usd", "latency_ms"):
                    item[key] = None
            out.append(item)
        return out

    def details(self, run_id: str, *, project_id: str = "") -> Optional[Dict[str, Any]]:
        sql = "SELECT * FROM query_runs WHERE run_id=?"
        params: List[Any] = [run_id]
        if project_id:
            sql += " AND project_id=?"; params.append(project_id)
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
            if not row:
                return None
            steps = [dict(r) for r in conn.execute(
                "SELECT * FROM query_steps WHERE run_id=? ORDER BY seq", [run_id]
            ).fetchall()]
            calls = [dict(r) for r in conn.execute(
                "SELECT * FROM llm_calls WHERE run_id=? ORDER BY created_at", [run_id]
            ).fetchall()]
        return {"run": dict(row), "steps": steps, "llm_calls": calls}


def get_run_store() -> RunStore:
    return RunStore.instance()


__all__ = ["RunStore", "current_run_id_var", "get_run_store"]
