"""Delay-event candidate store — analyst lifecycle over containment-validated
event candidates.

Candidates come from `build_event_register` (LLM extraction + deterministic
containment guard: date + actor/quote must appear verbatim in the evidence
snippet — the LLM cannot invent an event). Each candidate carries its source
(file/doc/page), date, and quote. An analyst then confirms / rejects / merges
them; only CONFIRMED candidates are treated as events for downstream claim use.

Backed by the shared learning DuckDB (`delay_event_candidates` table). Isolated
from the enrichment-owned events.db. All writes best-effort; never raise.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

STATUS_CANDIDATE = "candidate"
STATUS_CONFIRMED = "confirmed"
STATUS_REJECTED = "rejected"
STATUS_MERGED = "merged"

_COLS = ["candidate_id", "corpus", "project_id", "topic", "event_date",
         "actor", "issue", "quote", "file_name", "doc_id", "page_number",
         "support_level", "status", "merged_into", "created_at", "decided_at",
         "decided_by", "reason"]


def _candidate_id(corpus: str, project_id: str, doc_id: str,
                  event_date: str, quote: str) -> str:
    # Corpus/project-scoped: the same doc/date/quote in a different project is a
    # distinct candidate (avoids cross-project row collision under INSERT OR IGNORE).
    return hashlib.sha256(
        f"{corpus}|{project_id}|{doc_id}|{event_date}|{quote[:120]}"
        .encode("utf-8")).hexdigest()[:24]


def add_candidates(entries: List[Any], corpus: str = "",
                   project_id: Optional[str] = None,
                   topic: str = "") -> Dict[str, Any]:
    """Persist RegisterEntry candidates (status='candidate'). Idempotent by
    (doc_id, date, quote). Returns {ok, added, ids}. Never raises."""
    try:
        from src.learning.memory_store import get_memory_store
        store = get_memory_store()
        now = datetime.now().isoformat()
        ids: List[str] = []
        with store.lock:
            before = int(store.con.execute(
                "SELECT COUNT(*) FROM delay_event_candidates").fetchone()[0])
            for e in entries or []:
                cid = _candidate_id(corpus, project_id or "",
                                    getattr(e, "doc_id", ""),
                                    getattr(e, "event_date", ""),
                                    getattr(e, "quote", ""))
                ids.append(cid)
                store.con.execute(
                    "INSERT OR IGNORE INTO delay_event_candidates VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [cid, corpus, project_id or "", topic,
                     getattr(e, "event_date", ""), getattr(e, "actor", ""),
                     getattr(e, "issue", ""), getattr(e, "quote", "")[:1000],
                     getattr(e, "file_name", ""), getattr(e, "doc_id", ""),
                     int(getattr(e, "page_number", 0) or 0),
                     getattr(e, "support_level", ""), STATUS_CANDIDATE, "",
                     now, "", "", ""])
            added = int(store.con.execute(
                "SELECT COUNT(*) FROM delay_event_candidates").fetchone()[0]) - before
        return {"ok": True, "added": added, "ids": ids}
    except Exception as e:
        logger.warning(f"[CandidateStore] add failed: {e}")
        return {"ok": False, "added": 0, "ids": []}


def list_candidates(corpus: str = "", project_id: Optional[str] = None,
                    status: Optional[str] = None,
                    topic: Optional[str] = None,
                    limit: int = 200) -> List[Dict[str, Any]]:
    """Candidates, optionally filtered. Never raises."""
    try:
        from src.learning.memory_store import get_memory_store
        store = get_memory_store()
        where, params = [], []
        if corpus:
            where.append("corpus = ?"); params.append(corpus)
        if project_id:
            where.append("project_id = ?"); params.append(project_id)
        if status:
            where.append("status = ?"); params.append(status)
        if topic:
            where.append("topic = ?"); params.append(topic)
        sql = f"SELECT {', '.join(_COLS)} FROM delay_event_candidates"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY event_date LIMIT ?"
        params.append(limit)
        with store.lock:
            rows = store.con.execute(sql, params).fetchall()
        return [dict(zip(_COLS, r)) for r in rows]
    except Exception as e:
        logger.debug(f"[CandidateStore] list failed: {e}")
        return []


def set_status(candidate_id: str, status: str, decided_by: str = "",
               reason: str = "") -> Dict[str, Any]:
    """Confirm or reject one candidate. Rejection requires a reason (audit
    trail; nothing is hard-deleted). Returns {ok, ...}. Never raises."""
    if status not in (STATUS_CONFIRMED, STATUS_REJECTED, STATUS_CANDIDATE):
        return {"ok": False, "reason": f"invalid status '{status}'"}
    if status == STATUS_REJECTED and not (reason or "").strip():
        return {"ok": False, "reason": "a rejection reason is required"}
    try:
        from src.learning.memory_store import get_memory_store
        store = get_memory_store()
        with store.lock:
            exists = store.con.execute(
                "SELECT COUNT(*) FROM delay_event_candidates WHERE "
                "candidate_id = ?", [candidate_id]).fetchone()[0]
            if not exists:
                return {"ok": False, "reason": "unknown candidate_id"}
            store.con.execute(
                "UPDATE delay_event_candidates SET status = ?, decided_at = ?, "
                "decided_by = ?, reason = ? WHERE candidate_id = ?",
                [status, datetime.now().isoformat(), decided_by, reason,
                 candidate_id])
        return {"ok": True, "candidate_id": candidate_id, "status": status}
    except Exception as e:
        logger.warning(f"[CandidateStore] set_status failed: {e}")
        return {"ok": False, "reason": str(e)[:200]}


def get_candidate(candidate_id: str) -> Optional[Dict[str, Any]]:
    """One candidate by id (source/date/quote/status), or None. Never raises."""
    if not candidate_id:
        return None
    try:
        from src.learning.memory_store import get_memory_store
        store = get_memory_store()
        with store.lock:
            row = store.con.execute(
                f"SELECT {', '.join(_COLS)} FROM delay_event_candidates "
                "WHERE candidate_id = ?", [candidate_id]).fetchone()
        return dict(zip(_COLS, row)) if row else None
    except Exception as e:
        logger.debug(f"[CandidateStore] get_candidate failed: {e}")
        return None


def merge(primary_id: str, other_ids: List[str],
          decided_by: str = "") -> Dict[str, Any]:
    """Merge duplicate candidates into a primary; others → status='merged',
    merged_into=primary. Idempotent. Never raises."""
    other_ids = [o for o in (other_ids or []) if o and o != primary_id]
    if not primary_id or not other_ids:
        return {"ok": False, "reason": "primary_id and other_ids required"}
    try:
        from src.learning.memory_store import get_memory_store
        store = get_memory_store()
        now = datetime.now().isoformat()
        with store.lock:
            exists = store.con.execute(
                "SELECT COUNT(*) FROM delay_event_candidates WHERE "
                "candidate_id = ?", [primary_id]).fetchone()[0]
            if not exists:
                return {"ok": False, "reason": "unknown primary_id"}
            for oid in other_ids:
                store.con.execute(
                    "UPDATE delay_event_candidates SET status = ?, "
                    "merged_into = ?, decided_at = ?, decided_by = ? "
                    "WHERE candidate_id = ?",
                    [STATUS_MERGED, primary_id, now, decided_by, oid])
        return {"ok": True, "primary_id": primary_id,
                "merged": len(other_ids)}
    except Exception as e:
        logger.warning(f"[CandidateStore] merge failed: {e}")
        return {"ok": False, "reason": str(e)[:200]}


def confirmed_events(corpus: str = "",
                     project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Analyst-confirmed events (the only ones fit for downstream claim use)."""
    return list_candidates(corpus=corpus, project_id=project_id,
                           status=STATUS_CONFIRMED)
