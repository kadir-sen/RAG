"""Durable background queue for Chronology and Forensic report generation."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from src.config import STORAGE_DIR


DB_PATH = Path(STORAGE_DIR) / "report_jobs.db"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS report_jobs (
    job_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, username TEXT NOT NULL,
    module TEXT NOT NULL, title TEXT NOT NULL, request_json TEXT NOT NULL,
    sequence_number INTEGER,
    status TEXT NOT NULL, stage TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
    error TEXT, result_json TEXT, docx_path TEXT, created_at TEXT NOT NULL,
    started_at TEXT, completed_at TEXT, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_report_jobs_project ON report_jobs(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_report_jobs_queue ON report_jobs(status, created_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReportJobStore:
    _instance: Optional["ReportJobStore"] = None
    _instance_lock = threading.Lock()

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path); self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(report_jobs)")}
            if "sequence_number" not in columns:
                conn.execute("ALTER TABLE report_jobs ADD COLUMN sequence_number INTEGER")
            self._backfill_sequences(conn)
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_report_jobs_chronology_sequence "
                "ON report_jobs(project_id, sequence_number) "
                "WHERE module='chronology' AND sequence_number IS NOT NULL"
            )

    @staticmethod
    def _backfill_sequences(conn: sqlite3.Connection) -> None:
        """Assign stable per-project chronology numbers to pre-migration jobs."""
        projects = conn.execute(
            "SELECT DISTINCT project_id FROM report_jobs WHERE module='chronology'"
        ).fetchall()
        for project in projects:
            rows = conn.execute(
                "SELECT job_id FROM report_jobs WHERE project_id=? AND module='chronology' "
                "ORDER BY created_at, job_id", [project[0]],
            ).fetchall()
            # Negative temporary values avoid transient collisions when an
            # already-indexed database is repaired or deterministically
            # resequenced after an interrupted migration.
            for sequence, row in enumerate(rows, 1):
                conn.execute(
                    "UPDATE report_jobs SET sequence_number=? WHERE job_id=?",
                    [-sequence, row[0]],
                )
            for sequence, row in enumerate(rows, 1):
                conn.execute(
                    "UPDATE report_jobs SET sequence_number=? WHERE job_id=?",
                    [sequence, row[0]],
                )

    @classmethod
    def instance(cls) -> "ReportJobStore":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=20); conn.row_factory = sqlite3.Row
        try:
            yield conn; conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _row(row: sqlite3.Row) -> Dict:
        item = dict(row)
        for old, new in (("request_json", "request"), ("result_json", "result")):
            raw = item.pop(old, None)
            try:
                item[new] = json.loads(raw) if raw else None
            except Exception:
                item[new] = None
        if item.get("module") == "chronology":
            item["report_url"] = f"/chronology/reports/{item['job_id']}"
        return item

    def enqueue(self, *, project_id: str, username: str, module: str,
                title: str, request: Dict) -> Dict:
        if module not in ("chronology", "forensic"):
            raise ValueError("unsupported report module")
        job_id = uuid.uuid4().hex[:20]; now = _now()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            sequence_number = None
            if module == "chronology":
                sequence_number = conn.execute(
                    "SELECT COALESCE(MAX(sequence_number),0)+1 FROM report_jobs "
                    "WHERE project_id=? AND module='chronology'", [project_id],
                ).fetchone()[0]
            conn.execute(
                "INSERT INTO report_jobs "
                "(job_id,project_id,username,module,title,request_json,sequence_number,"
                "status,stage,progress,error,result_json,docx_path,created_at,started_at,"
                "completed_at,updated_at) VALUES (?,?,?,?,?,?,?,'queued','research',0,"
                "NULL,NULL,NULL,?,NULL,NULL,?)",
                [job_id, project_id, username, module, title[:300],
                 json.dumps(request, ensure_ascii=False), sequence_number, now, now],
            )
            row = conn.execute("SELECT * FROM report_jobs WHERE job_id=?", [job_id]).fetchone()
        return self._row(row)

    def recover(self) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE report_jobs SET status='queued', stage='research', progress=0, "
                "error=NULL, updated_at=? WHERE status='processing'", [_now()]
            )
        return cur.rowcount

    def claim_next(self) -> Optional[Dict]:
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM report_jobs WHERE status='queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if not row:
                return None
            now = _now()
            conn.execute(
                "UPDATE report_jobs SET status='processing',stage='research',progress=.05,"
                "started_at=COALESCE(started_at,?),updated_at=? WHERE job_id=?",
                [now, now, row["job_id"]],
            )
            row = conn.execute("SELECT * FROM report_jobs WHERE job_id=?", [row["job_id"]]).fetchone()
        return self._row(row)

    def update(self, job_id: str, stage: str, progress: float) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE report_jobs SET stage=?,progress=?,updated_at=? WHERE job_id=?",
                [stage, max(0, min(1, progress)), _now(), job_id],
            )

    def complete(self, job_id: str, result: Dict, docx_path: str) -> None:
        safe_result = {k: v for k, v in result.items() if k != "docx"}
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE report_jobs SET status='ready',stage='ready',progress=1,error=NULL,"
                "result_json=?,docx_path=?,completed_at=?,updated_at=? WHERE job_id=?",
                [json.dumps(safe_result, ensure_ascii=False), docx_path, _now(), _now(), job_id],
            )

    def replace_ready_result(self, job_id: str, result: Dict, docx_path: str) -> None:
        """Persist a user-reviewed draft/issue without changing job identity."""
        safe_result = {k: v for k, v in result.items() if k != "docx"}
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE report_jobs SET result_json=?,docx_path=?,updated_at=? "
                "WHERE job_id=? AND status='ready'",
                [json.dumps(safe_result, ensure_ascii=False), docx_path, _now(), job_id],
            )

    def fail(self, job_id: str, error: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE report_jobs SET status='failed',error=?,completed_at=?,updated_at=? WHERE job_id=?",
                [(error or "unknown error")[:3000], _now(), _now(), job_id],
            )

    def credit_exhausted(self, job_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE report_jobs SET status='credit_balance_exhausted',"
                "stage='credit_balance_exhausted',error='credit_balance_exhausted',"
                "completed_at=?,updated_at=? WHERE job_id=?",
                [_now(), _now(), job_id],
            )

    def get(self, job_id: str, project_id: str) -> Optional[Dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM report_jobs WHERE job_id=? AND project_id=?", [job_id, project_id]
            ).fetchone()
        return self._row(row) if row else None

    def list_project(self, project_id: str, module: str = "") -> List[Dict]:
        sql = "SELECT * FROM report_jobs WHERE project_id=?"; params: List = [project_id]
        if module:
            sql += " AND module=?"; params.append(module)
        sql += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row(r) for r in rows]


_stop = threading.Event(); _threads: List[threading.Thread] = []; _lock = threading.Lock()


def _worker() -> None:
    store = get_report_job_store()
    while not _stop.is_set():
        job = store.claim_next()
        if not job:
            _stop.wait(.5); continue
        from src.project_context import set_current_project
        from src.run_store import get_run_store
        from backend.core.security import set_current_user_context
        set_current_user_context(job["username"])
        set_current_project(job["project_id"], "editor")
        run = get_run_store(); run.start(
            run_id=job["job_id"], project_id=job["project_id"], username=job["username"],
            module=job["module"], query=job["title"], prompt_version="evidence-report-v1",
        )
        try:
            request = dict(job["request"] or {})
            if job["module"] == "chronology":
                request["issue_number"] = int(job["sequence_number"])
            store.update(job["job_id"], "retrieval", .2)
            from src.ai_reports import generate_chronology, generate_forensic
            fn = generate_chronology if job["module"] == "chronology" else generate_forensic
            result = fn(project_id=job["project_id"], **request)
            store.update(job["job_id"], "word", .9)
            out_dir = Path(STORAGE_DIR) / "projects" / job["project_id"] / "reports"
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"{job['job_id']}.docx"; path.write_bytes(result["docx"])
            store.complete(job["job_id"], result, str(path))
            run.finish(job["job_id"], route=job["module"],
                       source_count=len(result.get("evidence", [])),
                       footnote_count=int(result.get("audit", {}).get("footnote_records", 0)),
                       verification="PASS" if not result.get("removed_claims") else "FILTERED")
        except Exception as exc:
            from src.billing_store import CreditBalanceExceededError
            exhausted = isinstance(exc, CreditBalanceExceededError)
            if exhausted:
                store.credit_exhausted(job["job_id"])
            else:
                store.fail(job["job_id"], str(exc))
            run.finish(
                job["job_id"], status="failed", route=job["module"],
                error="credit_balance_exhausted" if exhausted else str(exc),
            )


def start_report_workers() -> None:
    with _lock:
        if any(t.is_alive() for t in _threads):
            return
        _stop.clear(); get_report_job_store().recover()
        thread = threading.Thread(target=_worker, name="report-worker", daemon=True)
        thread.start(); _threads.append(thread)


def stop_report_workers() -> None:
    _stop.set()
    for t in list(_threads): t.join(timeout=2)
    _threads.clear()


def get_report_job_store() -> ReportJobStore:
    return ReportJobStore.instance()


__all__ = ["get_report_job_store", "start_report_workers", "stop_report_workers"]
