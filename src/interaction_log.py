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
        # Trust Guard telemetry: one row per chat query (skipped runs included —
        # they are the coverage denominator for the admin stats).
        self._con.execute(
            "CREATE TABLE IF NOT EXISTS trust_guard_runs ("
            "run_id VARCHAR PRIMARY KEY, ts VARCHAR, username VARCHAR, query VARCHAR, "
            "route VARCHAR, risk VARCHAR, routing_confidence DOUBLE, "
            "action VARCHAR, sufficiency DOUBLE, unknown_entities INTEGER, "
            "re_retrieved BOOLEAN, llm_calls INTEGER, latency_ms DOUBLE, "
            "skipped BOOLEAN, skipped_reason VARCHAR)"
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

    # ── Trust Guard telemetry ─────────────────────────────────────────────
    def log_trust_guard_run(self, run_id: str = "", username: str = "", query: str = "",
                            route: str = "", risk: str = "",
                            routing_confidence: Optional[float] = None,
                            action: str = "", sufficiency: float = 0.0,
                            unknown_entities: int = 0, re_retrieved: bool = False,
                            llm_calls: int = 0, latency_ms: float = 0.0,
                            skipped: bool = False, skipped_reason: str = "",
                            ts: str = "") -> None:
        """Record one Trust Guard evaluation (guarded OR skipped). Best-effort."""
        rid = run_id or hashlib.sha256(f"{ts}|{username}|{query}".encode()).hexdigest()[:24]
        try:
            conf = float(routing_confidence) if routing_confidence is not None else None
        except (TypeError, ValueError):
            conf = None
        try:
            with self._db_lock:
                self._con.execute(
                    "INSERT OR IGNORE INTO trust_guard_runs VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [rid, ts, username, (query or "")[:2000], route, risk, conf,
                     action, float(sufficiency or 0.0), int(unknown_entities or 0),
                     bool(re_retrieved), int(llm_calls or 0), float(latency_ms or 0.0),
                     bool(skipped), skipped_reason],
                )
        except Exception as e:
            logger.debug(f"[InteractionLog] trust_guard_run skipped: {e}")

    def trust_guard_stats(self, days: int = 30) -> Dict:
        """Aggregate Trust Guard stats over the last `days` days."""
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        empty = {
            "total_runs": 0, "guarded": 0, "skipped": 0, "coverage_pct": 0.0,
            "actions": {}, "skip_reasons": {}, "risk": {},
            "avg_latency_ms": 0.0, "p95_latency_ms": 0.0, "avg_llm_calls": 0.0,
            "catches": {"unknown_entity_runs": 0, "re_retrievals": 0,
                        "rewrites_or_refusals": 0},
        }
        try:
            with self._db_lock:
                total, guarded = self._con.execute(
                    "SELECT COUNT(*), COALESCE(SUM(CASE WHEN NOT skipped THEN 1 ELSE 0 END), 0) "
                    "FROM trust_guard_runs WHERE ts >= ?", [cutoff],
                ).fetchone()
                if not total:
                    return empty
                actions = dict(self._con.execute(
                    "SELECT action, COUNT(*) FROM trust_guard_runs "
                    "WHERE ts >= ? AND NOT skipped GROUP BY action", [cutoff],
                ).fetchall())
                skip_reasons = dict(self._con.execute(
                    "SELECT skipped_reason, COUNT(*) FROM trust_guard_runs "
                    "WHERE ts >= ? AND skipped GROUP BY skipped_reason", [cutoff],
                ).fetchall())
                risk = dict(self._con.execute(
                    "SELECT risk, COUNT(*) FROM trust_guard_runs "
                    "WHERE ts >= ? GROUP BY risk", [cutoff],
                ).fetchall())
                lat = self._con.execute(
                    "SELECT COALESCE(AVG(latency_ms), 0), "
                    "COALESCE(quantile_cont(latency_ms, 0.95), 0), "
                    "COALESCE(AVG(llm_calls), 0) "
                    "FROM trust_guard_runs WHERE ts >= ? AND NOT skipped", [cutoff],
                ).fetchone()
                catches = self._con.execute(
                    "SELECT COALESCE(SUM(CASE WHEN unknown_entities > 0 THEN 1 ELSE 0 END), 0), "
                    "COALESCE(SUM(CASE WHEN re_retrieved THEN 1 ELSE 0 END), 0), "
                    "COALESCE(SUM(CASE WHEN action IN ('rewrite','refuse') THEN 1 ELSE 0 END), 0) "
                    "FROM trust_guard_runs WHERE ts >= ? AND NOT skipped", [cutoff],
                ).fetchone()
            return {
                "total_runs": int(total),
                "guarded": int(guarded),
                "skipped": int(total) - int(guarded),
                "coverage_pct": round(100.0 * int(guarded) / int(total), 1),
                "actions": {str(k): int(v) for k, v in actions.items()},
                "skip_reasons": {str(k): int(v) for k, v in skip_reasons.items()},
                "risk": {str(k): int(v) for k, v in risk.items()},
                "avg_latency_ms": round(float(lat[0]), 1),
                "p95_latency_ms": round(float(lat[1]), 1),
                "avg_llm_calls": round(float(lat[2]), 2),
                "catches": {
                    "unknown_entity_runs": int(catches[0]),
                    "re_retrievals": int(catches[1]),
                    "rewrites_or_refusals": int(catches[2]),
                },
            }
        except Exception as e:
            logger.debug(f"[InteractionLog] trust_guard_stats failed: {e}")
            return empty

    def trust_guard_recent(self, limit: int = 50) -> List[Dict]:
        """Most recent Trust Guard runs for the admin panel."""
        try:
            with self._db_lock:
                rows = self._con.execute(
                    "SELECT ts, username, query, route, risk, action, sufficiency, "
                    "latency_ms, skipped, skipped_reason FROM trust_guard_runs "
                    "ORDER BY ts DESC LIMIT ?", [limit],
                ).fetchall()
            return [{"ts": r[0], "username": r[1], "query": r[2], "route": r[3],
                     "risk": r[4], "action": r[5], "sufficiency": float(r[6] or 0.0),
                     "latency_ms": float(r[7] or 0.0), "skipped": bool(r[8]),
                     "skipped_reason": r[9]} for r in rows]
        except Exception as e:
            logger.debug(f"[InteractionLog] trust_guard_recent failed: {e}")
            return []

    def recent(self, limit: int = 200) -> List[Dict]:
        rows = self._con.execute(
            "SELECT query, route, source_files, scope, verdict FROM interactions "
            "ORDER BY ts DESC LIMIT ?", [limit],
        ).fetchall()
        return [{"query": r[0], "route": r[1],
                 "source_files": json.loads(r[2] or "[]"),
                 "scope": json.loads(r[3] or "{}"), "verdict": r[4]} for r in rows]


_instance: Optional[InteractionLog] = None


def get_interaction_log() -> InteractionLog:
    global _instance
    if _instance is None:
        _instance = InteractionLog()
    return _instance
