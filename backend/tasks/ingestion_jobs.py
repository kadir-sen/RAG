"""Durable SQLite ingestion queue with restart recovery and measured ETA."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from src.config import INGEST_MAX_CONCURRENCY, STORAGE_DIR


DB_PATH = Path(STORAGE_DIR) / "ingestion_jobs.db"
TERMINAL = ("ready", "failed", "credit_balance_exhausted")
CALIBRATION_BATCH_SIZE = 20
STAGES = ("queued", "extracting", "ocr", "metadata", "chunking", "embedding", "indexing", "ready")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    job_id          TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL,
    file_id         TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    filename        TEXT NOT NULL,
    requested_by    TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL,
    stage           TEXT NOT NULL,
    progress        REAL NOT NULL DEFAULT 0,
    error           TEXT,
    details_json    TEXT NOT NULL DEFAULT '{}',
    attempts        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    completed_at    TEXT,
    updated_at      TEXT NOT NULL,
    UNIQUE(project_id, file_id)
);
CREATE INDEX IF NOT EXISTS idx_ingestion_queue
    ON ingestion_jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_ingestion_project
    ON ingestion_jobs(project_id, updated_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class IngestionJobStore:
    _instance: Optional["IngestionJobStore"] = None
    _instance_lock = threading.Lock()

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(ingestion_jobs)")}
            if "requested_by" not in columns:
                conn.execute("ALTER TABLE ingestion_jobs ADD COLUMN requested_by TEXT NOT NULL DEFAULT ''")

    @classmethod
    def instance(cls) -> "IngestionJobStore":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=20)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _row(row: sqlite3.Row) -> Dict:
        item = dict(row)
        try:
            item["details"] = json.loads(item.pop("details_json") or "{}")
        except Exception:
            item["details"] = {}
        return item

    def recover_interrupted(self) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE ingestion_jobs SET status='queued', stage='queued', "
                "error=NULL, updated_at=? WHERE status='processing'",
                [_now()],
            )
        return cur.rowcount

    def enqueue(self, project_id: str, file_id: str, file_path: str, filename: str,
                requested_by: str = "") -> Dict:
        if not project_id:
            raise ValueError("project_id is required")
        job_id = uuid.uuid4().hex[:20]
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO ingestion_jobs "
                "(job_id,project_id,file_id,file_path,filename,requested_by,status,stage,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,'queued','queued',?,?) "
                "ON CONFLICT(project_id,file_id) DO UPDATE SET "
                "file_path=excluded.file_path, filename=excluded.filename, "
                "requested_by=CASE WHEN excluded.requested_by<>'' THEN excluded.requested_by "
                "ELSE ingestion_jobs.requested_by END, "
                "status=CASE WHEN ingestion_jobs.status='ready' THEN 'ready' ELSE 'queued' END, "
                "stage=CASE WHEN ingestion_jobs.status='ready' THEN 'ready' ELSE 'queued' END, "
                "progress=CASE WHEN ingestion_jobs.status='ready' THEN ingestion_jobs.progress ELSE 0 END, "
                "error=NULL, completed_at=CASE WHEN ingestion_jobs.status='ready' "
                "THEN ingestion_jobs.completed_at ELSE NULL END, updated_at=excluded.updated_at",
                [job_id, project_id, file_id, file_path, filename, requested_by, now, now],
            )
            row = conn.execute(
                "SELECT * FROM ingestion_jobs WHERE project_id=? AND file_id=?",
                [project_id, file_id],
            ).fetchone()
        return self._row(row)

    def claim_next(self) -> Optional[Dict]:
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            candidates = conn.execute(
                "SELECT * FROM ingestion_jobs WHERE status='queued' "
                "ORDER BY created_at, rowid"
            ).fetchall()
            row = None
            for candidate in candidates:
                first_batch = conn.execute(
                    "SELECT job_id,status FROM ingestion_jobs WHERE project_id=? "
                    "ORDER BY created_at,rowid LIMIT ?",
                    [candidate["project_id"], CALIBRATION_BATCH_SIZE],
                ).fetchall()
                first_ids = {item["job_id"] for item in first_batch}
                calibrated = bool(first_batch) and all(
                    item["status"] in TERMINAL for item in first_batch
                )
                if candidate["job_id"] in first_ids or calibrated:
                    row = candidate
                    break
            if not row:
                return None
            now = _now()
            conn.execute(
                "UPDATE ingestion_jobs SET status='processing', stage='extracting', "
                "progress=0.03, attempts=attempts+1, started_at=COALESCE(started_at,?), "
                "updated_at=? WHERE job_id=? AND status='queued'",
                [now, now, row["job_id"]],
            )
            row = conn.execute("SELECT * FROM ingestion_jobs WHERE job_id=?", [row["job_id"]]).fetchone()
        return self._row(row)

    def update(self, job_id: str, *, stage: Optional[str] = None,
               progress: Optional[float] = None, details: Optional[Dict] = None) -> None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT details_json FROM ingestion_jobs WHERE job_id=?", [job_id]
            ).fetchone()
            if not row:
                return
            try:
                merged = json.loads(row[0] or "{}")
            except Exception:
                merged = {}
            merged.update(details or {})
            conn.execute(
                "UPDATE ingestion_jobs SET stage=COALESCE(?,stage), "
                "progress=COALESCE(?,progress), details_json=?, updated_at=? WHERE job_id=?",
                [stage, max(0.0, min(1.0, progress)) if progress is not None else None,
                 json.dumps(merged, ensure_ascii=False), _now(), job_id],
            )

    def complete(self, job_id: str, details: Optional[Dict] = None) -> None:
        self.update(job_id, stage="ready", progress=1.0, details=details)
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE ingestion_jobs SET status='ready', completed_at=?, updated_at=? WHERE job_id=?",
                [_now(), _now(), job_id],
            )

    def fail(self, job_id: str, error: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE ingestion_jobs SET status='failed', error=?, completed_at=?, updated_at=? "
                "WHERE job_id=?",
                [(error or "unknown error")[:2000], _now(), _now(), job_id],
            )

    def credit_exhausted(self, job_id: str, error: str = "credit_balance_exhausted") -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE ingestion_jobs SET status='credit_balance_exhausted', "
                "stage='credit_balance_exhausted', error=?, completed_at=?, updated_at=? "
                "WHERE job_id=?",
                [(error or "credit_balance_exhausted")[:2000], _now(), _now(), job_id],
            )

    def get(self, job_id: str, project_id: str = "") -> Optional[Dict]:
        sql = "SELECT * FROM ingestion_jobs WHERE job_id=?"
        params: List = [job_id]
        if project_id:
            sql += " AND project_id=?"; params.append(project_id)
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return self._row(row) if row else None

    def get_by_file(self, file_id: str, project_id: str) -> Optional[Dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ingestion_jobs WHERE file_id=? AND project_id=?",
                [file_id, project_id],
            ).fetchone()
        return self._row(row) if row else None

    def list_project(self, project_id: str) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ingestion_jobs WHERE project_id=? ORDER BY created_at DESC",
                [project_id],
            ).fetchall()
        return [self._row(r) for r in rows]

    def project_summary(self, project_id: str) -> Dict:
        jobs = self.list_project(project_id)
        queued = sum(j["status"] == "queued" for j in jobs)
        processing = sum(j["status"] == "processing" for j in jobs)
        ready = sum(j["status"] == "ready" for j in jobs)
        failed = sum(j["status"] in ("failed", "credit_balance_exhausted") for j in jobs)
        durations = []
        for job in jobs:
            if not job.get("started_at") or not job.get("completed_at") or job["status"] != "ready":
                continue
            try:
                durations.append(
                    (datetime.fromisoformat(job["completed_at"]) -
                     datetime.fromisoformat(job["started_at"])).total_seconds()
                )
            except Exception:
                pass
        remaining = queued + processing
        first_batch = sorted(jobs, key=lambda j: (j["created_at"], j["job_id"]))[:CALIBRATION_BATCH_SIZE]
        calibration_complete = bool(first_batch) and all(
            j["status"] in TERMINAL for j in first_batch
        )
        eta = None
        if remaining and durations:
            mean = sum(durations[-20:]) / len(durations[-20:])
            eta = int(mean * remaining / max(1, int(INGEST_MAX_CONCURRENCY)))
        return {"queued": queued, "processing": processing, "ready": ready,
                "failed": failed, "eta_seconds": eta,
                "calibration_size": min(len(jobs), CALIBRATION_BATCH_SIZE),
                "calibration_complete": calibration_complete}


_stop = threading.Event()
_threads: List[threading.Thread] = []
_manager_lock = threading.Lock()


def _worker() -> None:
    store = get_ingestion_job_store()
    while not _stop.is_set():
        job = store.claim_next()
        if not job:
            _stop.wait(0.5)
            continue
        try:
            from backend.core.security import set_current_user_context
            # Worker threads are reused; clear stale attribution as well as
            # setting it for newly-created jobs.
            set_current_user_context(job.get("requested_by") or "")
            from backend.tasks.indexing import index_file_background
            index_file_background(
                job["file_id"], job["file_path"], project_id=job["project_id"],
                job_id=job["job_id"],
            )
        except Exception as exc:
            from src.billing_store import CreditBalanceExceededError
            if isinstance(exc, CreditBalanceExceededError):
                store.credit_exhausted(job["job_id"])
            else:
                store.fail(job["job_id"], str(exc))


def start_ingestion_workers() -> None:
    with _manager_lock:
        if any(t.is_alive() for t in _threads):
            return
        _stop.clear()
        store = get_ingestion_job_store()
        store.recover_interrupted()
        for idx in range(max(1, int(INGEST_MAX_CONCURRENCY))):
            thread = threading.Thread(target=_worker, name=f"ingestion-{idx+1}", daemon=True)
            thread.start()
            _threads.append(thread)


def stop_ingestion_workers() -> None:
    _stop.set()
    for thread in list(_threads):
        thread.join(timeout=2)
    _threads.clear()


def get_ingestion_job_store() -> IngestionJobStore:
    return IngestionJobStore.instance()


__all__ = [
    "IngestionJobStore", "get_ingestion_job_store", "start_ingestion_workers",
    "stop_ingestion_workers", "STAGES", "CALIBRATION_BATCH_SIZE",
]
