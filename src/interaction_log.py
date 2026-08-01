"""Interaction log — the feedback-FREE substrate the learning layers run on.

Plain RAG only improves when a human clicks 👍. This store instead records every
query the system answers (route, scope, which documents actually surfaced, and —
once the verify gate exists — whether the answer looked complete), so the system
can learn from its own usage with no human in the loop:

  * the **co-retrieval graph** counts which documents surface together for the same
    question; documents that keep co-occurring are related (event chains, "the
    drawings for area Y"), discovered passively with zero LLM cost.
  * the **weak-interaction** view (verify=WEAK / empty / scope-retry) is the
    self-supervised curriculum the periodic teacher (KOL C) mines for what to fix.

DuckDB-backed singleton, mirroring event_timeline. All writes are best-effort and
must never break a live query.

Schema:
  interactions(interaction_id, ts, username, query, route, source_files, scope, verdict)
  co_retrieval(doc_a, doc_b, cnt)   -- doc_a < doc_b canonical, undirected
"""
from __future__ import annotations

import hashlib
import json
import threading
from typing import Dict, List, Optional

import duckdb

from .config import STORAGE_DIR
from .logger import logger

INTERACTIONS_DIR = STORAGE_DIR / "interactions"
INTERACTIONS_DB = INTERACTIONS_DIR / "interactions.db"


class InteractionLog:
    """Singleton DuckDB store of answered queries + a co-retrieval graph."""

    _instance: Optional["InteractionLog"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._db_lock = threading.RLock()
                    inst._con = None
                    inst._init_db()
                    cls._instance = inst
        return cls._instance

    def _init_db(self):
        INTERACTIONS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            self._con = duckdb.connect(str(INTERACTIONS_DB))
        except Exception as e:
            logger.error(f"[InteractionLog] init failed ({e}); in-memory fallback")
            self._con = duckdb.connect(":memory:")
        self._con.execute(
            "CREATE TABLE IF NOT EXISTS interactions ("
            "interaction_id VARCHAR PRIMARY KEY, ts VARCHAR, username VARCHAR, "
            "query VARCHAR, route VARCHAR, source_files VARCHAR, scope VARCHAR, "
            "verdict VARCHAR)"
        )
        self._con.execute(
            "CREATE TABLE IF NOT EXISTS co_retrieval ("
            "doc_a VARCHAR, doc_b VARCHAR, cnt INTEGER, PRIMARY KEY (doc_a, doc_b))"
        )
        logger.info(f"[InteractionLog] Ready ({self.count()} interactions)")

    def count(self) -> int:
        return int(self._con.execute("SELECT COUNT(*) FROM interactions").fetchone()[0])

    def log(self, query: str, route: str = "", source_files: Optional[List[str]] = None,
            username: str = "", scope: Optional[Dict] = None, verdict: str = "",
            ts: str = "") -> None:
        """Record one answered query and bump the co-retrieval counts for the
        documents that surfaced together. Best-effort, non-fatal."""
        q = (query or "").strip()
        if not q:
            return
        files = [f for f in (source_files or []) if f]
        iid = hashlib.sha256(f"{ts}|{username}|{q}".encode("utf-8")).hexdigest()[:24]
        try:
            with self._db_lock:
                self._con.execute(
                    "INSERT OR IGNORE INTO interactions VALUES (?,?,?,?,?,?,?,?)",
                    [iid, ts, username, q[:2000], route,
                     json.dumps(files, ensure_ascii=False),
                     json.dumps(scope or {}, ensure_ascii=False), verdict],
                )
                self._bump_co_retrieval(files)
        except Exception as e:
            logger.debug(f"[InteractionLog] log skipped: {e}")

    def _bump_co_retrieval(self, files: List[str]) -> None:
        uniq = sorted(set(files))
        for i in range(len(uniq)):
            for j in range(i + 1, len(uniq)):
                a, b = uniq[i], uniq[j]
                self._con.execute(
                    "INSERT INTO co_retrieval VALUES (?,?,1) "
                    "ON CONFLICT (doc_a, doc_b) DO UPDATE SET cnt = cnt + 1",
                    [a, b],
                )

    # ── Passive structure: which documents relate to this one? ────────────
    def related_docs(self, file_name: str, limit: int = 10) -> List[Dict]:
        """Documents most often retrieved alongside `file_name`, by co-occurrence."""
        rows = self._con.execute(
            "SELECT CASE WHEN doc_a = ? THEN doc_b ELSE doc_a END AS other, cnt "
            "FROM co_retrieval WHERE doc_a = ? OR doc_b = ? ORDER BY cnt DESC LIMIT ?",
            [file_name, file_name, file_name, limit],
        ).fetchall()
        return [{"file_name": r[0], "count": int(r[1])} for r in rows]

    # ── Self-supervised curriculum for the teacher (KOL C) ────────────────
    def weak_interactions(self, limit: int = 100) -> List[Dict]:
        """Queries whose answer looked weak/empty — what the teacher should fix."""
        rows = self._con.execute(
            "SELECT query, route, source_files, scope FROM interactions "
            "WHERE verdict = 'WEAK' OR verdict = 'EMPTY' OR source_files = '[]' "
            "ORDER BY ts DESC LIMIT ?",
            [limit],
        ).fetchall()
        return [{"query": r[0], "route": r[1],
                 "source_files": json.loads(r[2] or "[]"),
                 "scope": json.loads(r[3] or "{}")} for r in rows]

    def recent(self, limit: int = 200) -> List[Dict]:
        rows = self._con.execute(
            "SELECT interaction_id, ts, username, query, route, source_files, scope, verdict FROM interactions "
            "ORDER BY ts DESC LIMIT ?", [limit],
        ).fetchall()
        return [{"interaction_id": r[0], "ts": r[1], "username": r[2],
                 "query": r[3], "route": r[4],
                 "source_files": json.loads(r[5] or "[]"),
                 "scope": json.loads(r[6] or "{}"), "verdict": r[7]} for r in rows]


_instance: Optional[InteractionLog] = None


def get_interaction_log() -> InteractionLog:
    global _instance
    if _instance is None:
        _instance = InteractionLog()
    return _instance
