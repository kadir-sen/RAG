"""Durable per-user credit, storage and provider-cost accounting.

Money never uses binary floating point in this module. Provider cost is stored
as nano-USD and balances as micro-credits (1 credit = USD 0.01).  The ledger is
append-only; mutable account rows are only an atomic balance/cache.
"""
from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from .config import STORAGE_DIR


DB_PATH = Path(STORAGE_DIR) / "users.db"
MICROCREDITS_PER_CREDIT = 1_000_000
NANOUSD_PER_USD = 1_000_000_000
USD_PER_CREDIT = Decimal("0.01")
DEMO_INITIAL_CREDITS = Decimal("1000")
DEMO_MARKUP_BPS = 3_000
DEMO_STORAGE_LIMIT_BYTES = 30_000_000_000
DEMO_MODEL_POLICY = "demo-gemini-3.6-v1"
PRICING_VERSION = "google-ai-2026-07-21"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS billing_accounts (
    username                 TEXT PRIMARY KEY,
    plan_type                TEXT NOT NULL DEFAULT 'legacy',
    credits_granted_micro    INTEGER NOT NULL DEFAULT 0,
    credits_balance_micro    INTEGER NOT NULL DEFAULT 0,
    markup_bps               INTEGER NOT NULL DEFAULT 3000,
    storage_limit_bytes      INTEGER NOT NULL DEFAULT 0,
    storage_used_bytes       INTEGER NOT NULL DEFAULT 0,
    model_policy             TEXT NOT NULL DEFAULT '',
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL,
    FOREIGN KEY(username) REFERENCES users(username) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS billing_ledger (
    event_id                 TEXT PRIMARY KEY,
    idempotency_key          TEXT UNIQUE,
    username                 TEXT NOT NULL,
    project_id               TEXT,
    run_id                   TEXT,
    job_id                   TEXT,
    event_type               TEXT NOT NULL,
    task_type                TEXT,
    provider                 TEXT,
    model                    TEXT,
    prompt_tokens            INTEGER NOT NULL DEFAULT 0,
    completion_tokens        INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens         INTEGER NOT NULL DEFAULT 0,
    cached_tokens            INTEGER NOT NULL DEFAULT 0,
    pricing_version          TEXT,
    provider_cost_nanos      INTEGER NOT NULL DEFAULT 0,
    retail_credit_micros     INTEGER NOT NULL DEFAULT 0,
    debited_credit_micros    INTEGER NOT NULL DEFAULT 0,
    uncovered_credit_micros  INTEGER NOT NULL DEFAULT 0,
    markup_bps               INTEGER NOT NULL DEFAULT 0,
    usage_source             TEXT NOT NULL DEFAULT 'provider',
    note                     TEXT,
    created_at               TEXT NOT NULL,
    FOREIGN KEY(username) REFERENCES users(username) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_billing_ledger_user_time
    ON billing_ledger(username, created_at);
CREATE INDEX IF NOT EXISTS idx_billing_ledger_project_time
    ON billing_ledger(project_id, created_at);
CREATE TRIGGER IF NOT EXISTS billing_ledger_no_update
BEFORE UPDATE ON billing_ledger
BEGIN
    SELECT RAISE(ABORT, 'billing ledger is append-only');
END;
CREATE TRIGGER IF NOT EXISTS billing_ledger_no_delete
BEFORE DELETE ON billing_ledger
BEGIN
    SELECT RAISE(ABORT, 'billing ledger is append-only');
END;
CREATE TABLE IF NOT EXISTS storage_objects (
    object_id       TEXT PRIMARY KEY,
    username        TEXT NOT NULL,
    project_id      TEXT NOT NULL,
    file_id         TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    deleted_at      TEXT,
    UNIQUE(project_id, file_id),
    FOREIGN KEY(username) REFERENCES users(username) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_storage_objects_user
    ON storage_objects(username, deleted_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_microcredits(value: Decimal | int | float | str) -> int:
    return int(
        (Decimal(str(value)) * MICROCREDITS_PER_CREDIT).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def _credits(micro: int) -> float:
    return float((Decimal(int(micro)) / MICROCREDITS_PER_CREDIT).quantize(Decimal("0.000001")))


class CreditBalanceExceededError(RuntimeError):
    def __init__(self, username: str):
        self.username = username
        super().__init__(f"Credit balance exhausted for {username}")


class StorageQuotaExceededError(RuntimeError):
    def __init__(self, username: str, used: int, limit: int, attempted: int):
        self.username = username
        self.used = used
        self.limit = limit
        self.attempted = attempted
        super().__init__(f"Storage quota exceeded for {username}: {used + attempted} / {limit}")


class BillingStore:
    _instance: Optional["BillingStore"] = None
    _instance_lock = threading.Lock()

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @classmethod
    def instance(cls) -> "BillingStore":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 20000")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def provision_account(
        self,
        username: str,
        *,
        plan_type: str = "legacy",
        initial_credits: Decimal | int | float | str = 0,
        markup_bps: int = DEMO_MARKUP_BPS,
        storage_limit_bytes: int = 0,
        model_policy: str = "",
    ) -> Dict[str, Any]:
        if plan_type not in ("legacy", "demo"):
            raise ValueError("unsupported plan_type")
        if plan_type == "demo":
            model_policy = model_policy or DEMO_MODEL_POLICY
            storage_limit_bytes = storage_limit_bytes or DEMO_STORAGE_LIMIT_BYTES
        if not 0 <= int(markup_bps) <= 100_000:
            raise ValueError("markup_bps must be between 0 and 100000")
        grant = max(0, _to_microcredits(initial_credits))
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            exists = conn.execute(
                "SELECT 1 FROM billing_accounts WHERE username=?", [username]
            ).fetchone()
            if exists:
                return self.summary(username, conn=conn)
            conn.execute(
                "INSERT INTO billing_accounts VALUES (?,?,?,?,?,?,?,?,?,?)",
                [username, plan_type, grant, grant, int(markup_bps),
                 max(0, int(storage_limit_bytes)), 0, model_policy, now, now],
            )
            if grant:
                conn.execute(
                    "INSERT INTO billing_ledger "
                    "(event_id,idempotency_key,username,event_type,retail_credit_micros,"
                    "debited_credit_micros,note,created_at) VALUES (?,?,?,?,?,?,?,?)",
                    [uuid.uuid4().hex, f"initial:{username}", username, "grant",
                     grant, 0, "Initial demo credit grant", now],
                )
            return self.summary(username, conn=conn)

    def get_account(self, username: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM billing_accounts WHERE username=?", [username]
            ).fetchone()
        return dict(row) if row else None

    def update_account(self, username: str, *, markup_percent: float | None = None,
                       storage_limit_bytes: int | None = None,
                       model_policy: str | None = None) -> Dict[str, Any]:
        sets: List[str] = []; params: List[Any] = []
        if markup_percent is not None:
            bps = round(float(markup_percent) * 100)
            if not 0 <= bps <= 100_000:
                raise ValueError("markup_percent must be between 0 and 1000")
            sets.append("markup_bps=?"); params.append(bps)
        if storage_limit_bytes is not None:
            if int(storage_limit_bytes) < 0:
                raise ValueError("storage_limit_bytes cannot be negative")
            sets.append("storage_limit_bytes=?"); params.append(int(storage_limit_bytes))
        if model_policy is not None:
            sets.append("model_policy=?"); params.append(str(model_policy))
        if not sets:
            return self.summary(username)
        sets.append("updated_at=?"); params.extend([_now(), username])
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                f"UPDATE billing_accounts SET {', '.join(sets)} WHERE username=?", params
            )
            if cur.rowcount == 0:
                raise ValueError("billing account not found")
        return self.summary(username)

    def summary(self, username: str, *, conn: sqlite3.Connection | None = None) -> Dict[str, Any]:
        owns = conn is None
        if owns:
            conn = sqlite3.connect(str(self.db_path), timeout=20)
            conn.row_factory = sqlite3.Row
        assert conn is not None
        try:
            row = conn.execute(
                "SELECT * FROM billing_accounts WHERE username=?", [username]
            ).fetchone()
            if not row:
                return {
                    "plan_type": "legacy", "credits_total": 0.0,
                    "credits_remaining": 0.0, "credits_used": 0.0,
                    "credit_percent_remaining": 100.0,
                    "storage_used_bytes": 0, "storage_limit_bytes": 0,
                    "storage_percent_used": 0.0, "model_policy": "",
                }
            granted = int(row["credits_granted_micro"])
            balance = int(row["credits_balance_micro"])
            used = int(conn.execute(
                "SELECT COALESCE(SUM(debited_credit_micros),0) FROM billing_ledger "
                "WHERE username=? AND event_type='charge'", [username]
            ).fetchone()[0])
            limit = int(row["storage_limit_bytes"])
            stored = int(row["storage_used_bytes"])
            return {
                "plan_type": row["plan_type"],
                "credits_total": _credits(granted),
                "credits_remaining": _credits(balance),
                "credits_used": _credits(used),
                "credit_percent_remaining": round(
                    max(0.0, min(100.0, balance * 100.0 / granted)), 2
                ) if granted > 0 else (100.0 if row["plan_type"] != "demo" else 0.0),
                "storage_used_bytes": stored,
                "storage_limit_bytes": limit,
                "storage_percent_used": round(
                    max(0.0, min(100.0, stored * 100.0 / limit)), 2
                ) if limit > 0 else 0.0,
                "markup_percent": int(row["markup_bps"]) / 100.0,
                "model_policy": row["model_policy"],
            }
        finally:
            if owns:
                conn.close()

    def enforce_credits(self, username: str) -> None:
        row = self.get_account(username)
        if row and row["plan_type"] == "demo" and int(row["credits_balance_micro"]) <= 0:
            raise CreditBalanceExceededError(username)

    def record_charge(
        self, *, username: str, project_id: str = "", run_id: str = "",
        job_id: str = "", task_type: str = "generation", provider: str,
        model: str, prompt_tokens: int, completion_tokens: int,
        reasoning_tokens: int = 0, cached_tokens: int = 0,
        provider_cost_nanos: int = 0, usage_source: str = "provider",
        pricing_version: str = PRICING_VERSION, idempotency_key: str = "",
        event_type: str = "charge", debit: bool = True,
    ) -> Dict[str, Any]:
        now = _now()
        key = idempotency_key or uuid.uuid4().hex
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            prior = conn.execute(
                "SELECT event_id FROM billing_ledger WHERE idempotency_key=?", [key]
            ).fetchone()
            if prior:
                return self.summary(username, conn=conn)
            account = conn.execute(
                "SELECT * FROM billing_accounts WHERE username=?", [username]
            ).fetchone()
            if not account:
                return self.summary(username, conn=conn)
            markup = int(account["markup_bps"])
            retail = int((
                Decimal(max(0, int(provider_cost_nanos))) / NANOUSD_PER_USD
                * (Decimal(10_000 + markup) / Decimal(10_000))
                / USD_PER_CREDIT * MICROCREDITS_PER_CREDIT
            ).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            balance = int(account["credits_balance_micro"])
            if account["plan_type"] == "demo" and debit:
                debited = min(balance, retail)
                uncovered = max(0, retail - debited)
                conn.execute(
                    "UPDATE billing_accounts SET credits_balance_micro=?,updated_at=? "
                    "WHERE username=?", [balance - debited, now, username]
                )
            else:
                debited = 0
                uncovered = 0
            conn.execute(
                "INSERT INTO billing_ledger VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [uuid.uuid4().hex, key, username, project_id or None, run_id or None,
                 job_id or None, event_type, task_type, provider, model,
                 max(0, int(prompt_tokens)), max(0, int(completion_tokens)),
                 max(0, int(reasoning_tokens)), max(0, int(cached_tokens)),
                 pricing_version, max(0, int(provider_cost_nanos)), retail, debited,
                 uncovered, markup, usage_source, None, now],
            )
            return self.summary(username, conn=conn)

    def adjust_credits(self, username: str, credits: Decimal | int | float | str,
                       note: str, *, idempotency_key: str = "") -> Dict[str, Any]:
        delta = _to_microcredits(credits)
        if delta == 0:
            raise ValueError("credit adjustment cannot be zero")
        if not (note or "").strip():
            raise ValueError("credit adjustment reason is required")
        now = _now(); key = idempotency_key or uuid.uuid4().hex
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM billing_ledger WHERE idempotency_key=?", [key]).fetchone():
                return self.summary(username, conn=conn)
            row = conn.execute(
                "SELECT * FROM billing_accounts WHERE username=?", [username]
            ).fetchone()
            if not row:
                raise ValueError("billing account not found")
            applied = delta if delta > 0 else -min(abs(delta), int(row["credits_balance_micro"]))
            granted = max(0, int(row["credits_granted_micro"]) + applied)
            balance = max(0, int(row["credits_balance_micro"]) + applied)
            conn.execute(
                "UPDATE billing_accounts SET credits_granted_micro=?,credits_balance_micro=?,"
                "updated_at=? WHERE username=?", [granted, balance, now, username]
            )
            conn.execute(
                "INSERT INTO billing_ledger "
                "(event_id,idempotency_key,username,event_type,retail_credit_micros,note,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                [uuid.uuid4().hex, key, username, "grant" if applied > 0 else "adjustment",
                 applied, note.strip(), now],
            )
            return self.summary(username, conn=conn)

    def register_storage(self, *, username: str, project_id: str, file_id: str,
                         file_path: str, size_bytes: int) -> Dict[str, Any]:
        size = max(0, int(size_bytes)); now = _now()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            old = conn.execute(
                "SELECT * FROM storage_objects WHERE project_id=? AND file_id=?",
                [project_id, file_id],
            ).fetchone()
            if old and old["deleted_at"] is None:
                return self.summary(username, conn=conn)
            account = conn.execute(
                "SELECT * FROM billing_accounts WHERE username=?", [username]
            ).fetchone()
            if not account:
                return self.summary(username, conn=conn)
            used = int(account["storage_used_bytes"]); limit = int(account["storage_limit_bytes"])
            if limit > 0 and used + size > limit:
                raise StorageQuotaExceededError(username, used, limit, size)
            if old:
                conn.execute(
                    "UPDATE storage_objects SET username=?,file_path=?,size_bytes=?,"
                    "created_at=?,deleted_at=NULL WHERE object_id=?",
                    [username, file_path, size, now, old["object_id"]],
                )
            else:
                conn.execute(
                    "INSERT INTO storage_objects VALUES (?,?,?,?,?,?,?,NULL)",
                    [uuid.uuid4().hex, username, project_id, file_id, file_path, size, now],
                )
            conn.execute(
                "UPDATE billing_accounts SET storage_used_bytes=storage_used_bytes+?,"
                "updated_at=? WHERE username=?", [size, now, username]
            )
            return self.summary(username, conn=conn)

    def release_storage(self, *, project_id: str, file_id: str) -> None:
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM storage_objects WHERE project_id=? AND file_id=? "
                "AND deleted_at IS NULL", [project_id, file_id]
            ).fetchone()
            if not row:
                return
            conn.execute("UPDATE storage_objects SET deleted_at=? WHERE object_id=?", [now, row["object_id"]])
            conn.execute(
                "UPDATE billing_accounts SET storage_used_bytes=MAX(0,storage_used_bytes-?),"
                "updated_at=? WHERE username=?", [int(row["size_bytes"]), now, row["username"]]
            )

    def usage(self, *, username: str = "", project_id: str = "", date_from: str = "",
              date_to: str = "") -> Dict[str, Any]:
        where = ["event_type IN ('charge','historical')"]; params: List[Any] = []
        for clause, value in (("username=?", username), ("project_id=?", project_id),
                              ("created_at>=?", date_from), ("created_at<=?", date_to)):
            if value:
                where.append(clause); params.append(value)
        sql = (
            "SELECT project_id,username,provider,model,task_type,pricing_version,"
            "usage_source,markup_bps,COUNT(*) calls,SUM(prompt_tokens) prompt_tokens,"
            "SUM(completion_tokens) completion_tokens,SUM(reasoning_tokens) reasoning_tokens,"
            "SUM(cached_tokens) cached_tokens,SUM(provider_cost_nanos) provider_cost_nanos,"
            "SUM(retail_credit_micros) retail_credit_micros,"
            "SUM(debited_credit_micros) debited_credit_micros,"
            "SUM(uncovered_credit_micros) uncovered_credit_micros,"
            "SUM(CASE WHEN retail_credit_micros>0 THEN provider_cost_nanos * "
            "(CAST(uncovered_credit_micros AS REAL)/retail_credit_micros) ELSE 0 END) "
            "uncovered_provider_cost_nanos "
            "FROM billing_ledger WHERE " + " AND ".join(where) +
            " GROUP BY project_id,username,provider,model,task_type,pricing_version,"
            "usage_source,markup_bps ORDER BY provider_cost_nanos DESC"
        )
        with self._connect() as conn:
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        for row in rows:
            row["estimated_provider_cost_usd"] = round(
                int(row.pop("provider_cost_nanos") or 0) / NANOUSD_PER_USD, 9
            )
            row["uncovered_provider_cost_usd"] = round(
                float(row.pop("uncovered_provider_cost_nanos") or 0) / NANOUSD_PER_USD, 9
            )
            row["markup_percent"] = int(row.pop("markup_bps") or 0) / 100.0
            for key in ("retail_credit_micros", "debited_credit_micros", "uncovered_credit_micros"):
                row[key.removesuffix("_micros")] = _credits(int(row.pop(key) or 0))
        return {"groups": rows}

    def job_usage(self, job_id: str) -> Dict[str, Any]:
        """Admin-safe exact token/cost totals for one background report job."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) calls,COALESCE(SUM(prompt_tokens),0) prompt_tokens,"
                "COALESCE(SUM(completion_tokens),0) completion_tokens,"
                "COALESCE(SUM(reasoning_tokens),0) reasoning_tokens,"
                "COALESCE(SUM(cached_tokens),0) cached_tokens,"
                "COALESCE(SUM(provider_cost_nanos),0) provider_cost_nanos,"
                "COALESCE(SUM(retail_credit_micros),0) retail_credit_micros,"
                "COALESCE(SUM(debited_credit_micros),0) debited_credit_micros,"
                "COALESCE(SUM(uncovered_credit_micros),0) uncovered_credit_micros "
                "FROM billing_ledger WHERE job_id=? AND event_type='charge'",
                [job_id],
            ).fetchone()
        value = dict(row)
        value["provider_cost_usd"] = round(
            int(value.pop("provider_cost_nanos") or 0) / NANOUSD_PER_USD, 9
        )
        for key in ("retail_credit_micros", "debited_credit_micros", "uncovered_credit_micros"):
            value[key.removesuffix("_micros")] = _credits(int(value.pop(key) or 0))
        return value


def get_billing_store() -> BillingStore:
    return BillingStore.instance()


__all__ = [
    "BillingStore", "CreditBalanceExceededError", "StorageQuotaExceededError",
    "DEMO_INITIAL_CREDITS", "DEMO_MARKUP_BPS", "DEMO_STORAGE_LIMIT_BYTES",
    "DEMO_MODEL_POLICY", "PRICING_VERSION", "get_billing_store",
]
