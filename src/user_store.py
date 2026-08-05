"""
User store — SQLite-backed user accounts, per-user token quota, feature flags.

Schema lives in `storage/users.db`. One row per user, one row per usage counter.
Password hashes use bcrypt. Auth itself happens in backend/core/security.py.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import bcrypt

from .config import STORAGE_DIR
from .logger import logger


DB_PATH = Path(STORAGE_DIR) / "users.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT    UNIQUE NOT NULL,
    display_name    TEXT,
    password_hash   TEXT    NOT NULL,
    role            TEXT    NOT NULL DEFAULT 'user',
    token_limit     INTEGER NOT NULL DEFAULT 1000000,
    features_json   TEXT    NOT NULL DEFAULT '{}',
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS user_usage (
    username          TEXT    PRIMARY KEY,
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_calls       INTEGER NOT NULL DEFAULT 0,
    updated_at        TEXT    NOT NULL,
    FOREIGN KEY(username) REFERENCES users(username) ON DELETE CASCADE
);
"""


class UserQuotaExceededError(RuntimeError):
    """Raised when a user has consumed their full token allowance."""

    def __init__(self, username: str, used: int, limit: int):
        self.username = username
        self.used = used
        self.limit = limit
        super().__init__(
            f"Token quota exceeded for {username}: {used} / {limit}"
        )


class UserStore:
    """SQLite-backed singleton user store. Thread-safe via per-connection locks."""

    _instance: Optional["UserStore"] = None
    _lock = threading.Lock()

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        self._init_schema()
        from .billing_store import BillingStore
        self.billing = BillingStore(self.db_path)
        # Schema migration: old accounts stay legacy/unlimited until explicitly
        # provisioned as demo accounts. This never converts historical tokens to
        # credits or silently places an existing customer behind a new paywall.
        for record in self.list_users():
            self.billing.provision_account(record["username"], plan_type="legacy")

    @classmethod
    def instance(cls) -> "UserStore":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # ── Helpers ─────────────────────────────────────────────

    @staticmethod
    def _hash_password(plain: str) -> str:
        return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    @staticmethod
    def _verify(plain: str, hashed: str) -> bool:
        try:
            return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
        except Exception:
            return False

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> Dict[str, Any]:
        try:
            features = json.loads(row["features_json"] or "{}")
        except Exception:
            features = {}
        return {
            "id": row["id"],
            "username": row["username"],
            "display_name": row["display_name"] or row["username"],
            "role": row["role"],
            "token_limit": int(row["token_limit"]),
            "features": features,
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # ── CRUD ────────────────────────────────────────────────

    def create_user(
        self,
        username: str,
        password: str,
        *,
        display_name: Optional[str] = None,
        role: str = "user",
        token_limit: int = 1_000_000,
        features: Optional[Dict[str, bool]] = None,
        plan_type: str = "legacy",
        initial_credits: float = 0,
        markup_percent: float = 30,
        storage_limit_bytes: int = 0,
        model_policy: str = "",
        provider_key_ref: str = "",
    ) -> Dict[str, Any]:
        if role not in ("user", "admin"):
            raise ValueError(f"invalid role: {role!r}")
        now = datetime.utcnow().isoformat()
        features_json = json.dumps(features or {})
        with self._write_lock, self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO users
                        (username, display_name, password_hash, role,
                         token_limit, features_json, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        username,
                        display_name,
                        self._hash_password(password),
                        role,
                        int(token_limit),
                        features_json,
                        now,
                        now,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO user_usage
                        (username, prompt_tokens, completion_tokens, total_calls, updated_at)
                    VALUES (?, 0, 0, 0, ?)
                    """,
                    (username, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"username already exists: {username}") from exc
        logger.info(f"[UserStore] Created user {username} (role={role})")
        self.billing.provision_account(
            username,
            plan_type=plan_type,
            initial_credits=initial_credits,
            markup_bps=round(float(markup_percent) * 100),
            storage_limit_bytes=storage_limit_bytes,
            model_policy=model_policy,
            provider_key_ref=provider_key_ref,
        )
        return self.get_user(username)

    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
        return self._row_to_user(row) if row else None

    def list_users(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM users ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_user(r) for r in rows]

    def update_user(self, username: str, **fields: Any) -> Optional[Dict[str, Any]]:
        allowed = {
            "display_name",
            "role",
            "token_limit",
            "features",
            "is_active",
            "password",
        }
        invalid = set(fields) - allowed
        if invalid:
            raise ValueError(f"cannot update fields: {invalid}")
        sets: List[str] = []
        params: List[Any] = []
        for key, value in fields.items():
            if key == "features":
                sets.append("features_json = ?")
                params.append(json.dumps(value or {}))
            elif key == "password":
                sets.append("password_hash = ?")
                params.append(self._hash_password(value))
            elif key == "is_active":
                sets.append("is_active = ?")
                params.append(1 if value else 0)
            elif key == "token_limit":
                sets.append("token_limit = ?")
                params.append(int(value))
            else:
                sets.append(f"{key} = ?")
                params.append(value)
        if not sets:
            return self.get_user(username)
        sets.append("updated_at = ?")
        params.append(datetime.utcnow().isoformat())
        params.append(username)
        with self._write_lock, self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE users SET {', '.join(sets)} WHERE username = ?", params
            )
            if cursor.rowcount == 0:
                return None
        return self.get_user(username)

    def delete_user(self, username: str, *, soft: bool = True) -> bool:
        with self._write_lock, self._connect() as conn:
            if soft:
                cursor = conn.execute(
                    "UPDATE users SET is_active = 0, updated_at = ? WHERE username = ?",
                    (datetime.utcnow().isoformat(), username),
                )
            else:
                cursor = conn.execute(
                    "DELETE FROM users WHERE username = ?", (username,)
                )
            return cursor.rowcount > 0

    # ── Auth ────────────────────────────────────────────────

    def verify_password(
        self, username: str, password: str
    ) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
        if not row:
            return None
        if not self._verify(password, row["password_hash"]):
            return None
        if not row["is_active"]:
            return None
        return self._row_to_user(row)

    # ── Usage ───────────────────────────────────────────────

    def increment_usage(
        self, username: str, prompt_tokens: int, completion_tokens: int
    ) -> None:
        if prompt_tokens <= 0 and completion_tokens <= 0:
            return
        now = datetime.utcnow().isoformat()
        with self._write_lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_usage (username, prompt_tokens, completion_tokens, total_calls, updated_at)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(username) DO UPDATE SET
                    prompt_tokens     = prompt_tokens + excluded.prompt_tokens,
                    completion_tokens = completion_tokens + excluded.completion_tokens,
                    total_calls       = total_calls + 1,
                    updated_at        = excluded.updated_at
                """,
                (
                    username,
                    int(max(0, prompt_tokens)),
                    int(max(0, completion_tokens)),
                    now,
                ),
            )

    def get_usage(self, username: str) -> Dict[str, Any]:
        with self._connect() as conn:
            urow = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
            if not urow:
                return {
                    "username": username,
                    "used_tokens": 0,
                    "token_limit": 0,
                    "percent_remaining": 0.0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_calls": 0,
                }
            row = conn.execute(
                "SELECT * FROM user_usage WHERE username = ?", (username,)
            ).fetchone()
        pt = int(row["prompt_tokens"]) if row else 0
        ct = int(row["completion_tokens"]) if row else 0
        used = pt + ct
        limit = int(urow["token_limit"])
        if limit <= 0:
            percent_remaining = 0.0
        else:
            percent_remaining = max(0.0, min(100.0, (1.0 - used / limit) * 100.0))
        return {
            "username": username,
            "used_tokens": used,
            "token_limit": limit,
            "percent_remaining": round(percent_remaining, 2),
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_calls": int(row["total_calls"]) if row else 0,
        }

    def get_billing_summary(self, username: str) -> Dict[str, Any]:
        """Return credit/storage state while preserving legacy token counters."""
        return {**self.get_usage(username), **self.billing.summary(username)}

    def reset_usage(self, username: str) -> Dict[str, Any]:
        now = datetime.utcnow().isoformat()
        with self._write_lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_usage (username, prompt_tokens, completion_tokens, total_calls, updated_at)
                VALUES (?, 0, 0, 0, ?)
                ON CONFLICT(username) DO UPDATE SET
                    prompt_tokens     = 0,
                    completion_tokens = 0,
                    total_calls       = 0,
                    updated_at        = excluded.updated_at
                """,
                (username, now),
            )
        return self.get_usage(username)

    def enforce_quota(self, username: str) -> None:
        """Raise UserQuotaExceededError if the user has consumed >= token_limit."""
        snapshot = self.get_usage(username)
        if snapshot["token_limit"] > 0 and snapshot["used_tokens"] >= snapshot["token_limit"]:
            raise UserQuotaExceededError(
                username, snapshot["used_tokens"], snapshot["token_limit"]
            )


def get_user_store() -> UserStore:
    return UserStore.instance()


__all__ = [
    "UserStore",
    "UserQuotaExceededError",
    "get_user_store",
    "DB_PATH",
]
