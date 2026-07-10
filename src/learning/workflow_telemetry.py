"""Workflow telemetry — one durable row per workflow run.

The learning substrate for the planner/resolver: which query went to which
workflow, whether it succeeded or fell back, which inputs were selected, and
(later) the user's feedback. Sprint 1 writes; query_patterns (Sprint 3) reads.
Best-effort: a telemetry failure must never break a workflow.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..logger import logger
from .memory_store import get_memory_store

_STOPWORDS = {
    "the", "a", "an", "of", "for", "to", "in", "on", "and", "or", "as", "is",
    "show", "me", "create", "make", "run", "give", "please", "this", "that",
    "with", "by", "per", "into", "from", "prepare", "generate", "build",
}


def query_signature(query: str) -> str:
    """Normalized core-term signature for grouping similar queries."""
    toks = re.findall(r"[a-z0-9]+", (query or "").lower())
    core = sorted({t for t in toks if t not in _STOPWORDS and len(t) > 1})
    return "|".join(core)


def _block_types(blocks: List[dict]) -> List[str]:
    return [b.get("type", "") for b in (blocks or []) if b.get("type")]


def record_workflow_run(wr: Any, ctx: Any, plan: Any,
                        latency_ms: float = 0.0,
                        username: str = "") -> None:
    """Append one workflow_runs row. Never raises."""
    try:
        store = get_memory_store()
        ts = datetime.now().isoformat()
        wid = getattr(getattr(wr, "workflow_id", None), "value",
                      str(getattr(wr, "workflow_id", "")))
        query = getattr(ctx, "user_query", "") or ""
        sig = query_signature(query)
        rid = hashlib.sha256(
            f"{ts}|{username}|{query}|{wid}".encode("utf-8")).hexdigest()[:24]
        fallback = ""
        if getattr(wr, "status", "") in ("partial", "failed", "unavailable"):
            fallback = getattr(wr, "status", "")
        row = [
            rid, ts, getattr(ctx, "corpus_id", "") or "",
            getattr(ctx, "project_id", None) or "", username, query[:2000], sig,
            wid, getattr(wr, "status", ""), getattr(plan, "source", ""),
            json.dumps(getattr(ctx, "selected_xers", []) or []),
            json.dumps(getattr(ctx, "selected_excel_tables", []) or []),
            json.dumps(getattr(ctx, "selected_documents", []) or []),
            (getattr(wr, "selected_inputs_summary", "") or "")[:4000],
            fallback,
            json.dumps(getattr(wr, "caveats", []) or [], ensure_ascii=False),
            json.dumps(_block_types(getattr(wr, "blocks", []))),
            bool(getattr(wr, "analyst_review_required", False)),
            float(latency_ms or 0.0),
            None,
        ]
        with store.lock:
            store.con.execute(
                "INSERT OR IGNORE INTO workflow_runs VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
    except Exception as e:
        logger.debug(f"[WorkflowTelemetry] record skipped: {e}")


def recent_runs(corpus: str = "", limit: int = 100) -> List[Dict[str, Any]]:
    """Most recent workflow runs, optionally scoped to a corpus."""
    try:
        store = get_memory_store()
        with store.lock:
            if corpus:
                rows = store.con.execute(
                    "SELECT user_query, workflow_id, status, query_signature "
                    "FROM workflow_runs WHERE corpus = ? ORDER BY ts DESC "
                    "LIMIT ?", [corpus, limit]).fetchall()
            else:
                rows = store.con.execute(
                    "SELECT user_query, workflow_id, status, query_signature "
                    "FROM workflow_runs ORDER BY ts DESC LIMIT ?",
                    [limit]).fetchall()
        return [{"user_query": r[0], "workflow_id": r[1], "status": r[2],
                 "query_signature": r[3]} for r in rows]
    except Exception as e:
        logger.debug(f"[WorkflowTelemetry] recent_runs failed: {e}")
        return []


def telemetry_summary(corpus: str = "", days: int = 30) -> Dict[str, Any]:
    """Aggregate workflow-run stats for an admin panel. Never raises."""
    empty = {"total_runs": 0, "by_workflow": {}, "by_status": {},
             "analyst_review_runs": 0, "avg_latency_ms": 0.0}
    try:
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        store = get_memory_store()
        corpus_clause = " AND corpus = ?" if corpus else ""
        params: List[Any] = [cutoff] + ([corpus] if corpus else [])
        with store.lock:
            total = int(store.con.execute(
                f"SELECT COUNT(*) FROM workflow_runs WHERE ts >= ?"
                f"{corpus_clause}", params).fetchone()[0])
            if not total:
                return empty
            by_wf = dict(store.con.execute(
                f"SELECT workflow_id, COUNT(*) FROM workflow_runs "
                f"WHERE ts >= ?{corpus_clause} GROUP BY workflow_id",
                params).fetchall())
            by_status = dict(store.con.execute(
                f"SELECT status, COUNT(*) FROM workflow_runs "
                f"WHERE ts >= ?{corpus_clause} GROUP BY status",
                params).fetchall())
            analyst = int(store.con.execute(
                f"SELECT COALESCE(SUM(CASE WHEN analyst_review_required "
                f"THEN 1 ELSE 0 END), 0) FROM workflow_runs WHERE ts >= ?"
                f"{corpus_clause}", params).fetchone()[0])
            avg_lat = float(store.con.execute(
                f"SELECT COALESCE(AVG(latency_ms), 0) FROM workflow_runs "
                f"WHERE ts >= ?{corpus_clause}", params).fetchone()[0])
        return {
            "total_runs": total,
            "by_workflow": {str(k): int(v) for k, v in by_wf.items()},
            "by_status": {str(k): int(v) for k, v in by_status.items()},
            "analyst_review_runs": analyst,
            "avg_latency_ms": round(avg_lat, 1),
        }
    except Exception as e:
        logger.debug(f"[WorkflowTelemetry] summary failed: {e}")
        return empty


def runs_for_query_signature(sig: str,
                             limit: int = 50) -> List[Dict[str, Any]]:
    """Prior runs sharing a normalized query signature (Sprint 3 planner read)."""
    try:
        store = get_memory_store()
        with store.lock:
            rows = store.con.execute(
                "SELECT workflow_id, status, COUNT(*) FROM workflow_runs "
                "WHERE query_signature = ? GROUP BY workflow_id, status "
                "ORDER BY COUNT(*) DESC LIMIT ?", [sig, limit]).fetchall()
        return [{"workflow_id": r[0], "status": r[1], "count": int(r[2])}
                for r in rows]
    except Exception as e:
        logger.debug(f"[WorkflowTelemetry] signature lookup failed: {e}")
        return []
