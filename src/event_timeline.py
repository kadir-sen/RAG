"""Event timeline store — a structured, queryable layer above flat RAG.

Classic RAG answers "what does the document say" but is weak at corpus-level,
chronological questions ("what delays happened on project X and why", "what
excuses were given, in order"). This store holds STRUCTURED events extracted from
documents (delay / disruption / excuse / decision / milestone / claim) with a
date, actor, reason, severity and status, so those questions are answered from a
deterministic timeline (DuckDB SQL) instead of nearest-neighbour vector search.

Events are produced by the unified ingest enrichment (file_router._enrich_document_llm
-> storage/enrichment/{doc_id}.json) and loaded here by scripts/build_event_timeline.py.

Schema: events(event_id, doc_id, file_name, project, date, date_sort, event_type,
                actor, reason, severity, status, description, source)
"""
from __future__ import annotations

import hashlib
import threading
from typing import Dict, List, Optional

import duckdb

from .config import STORAGE_DIR
from .logger import logger

EVENTS_DIR = STORAGE_DIR / "events"
EVENTS_DB = EVENTS_DIR / "events.db"

EVENT_TYPES = ("delay", "disruption", "excuse", "decision", "milestone", "claim")


def _event_id(doc_id: str, event_type: str, date: str, description: str) -> str:
    h = hashlib.sha256(f"{doc_id}|{event_type}|{date}|{description}".encode("utf-8")).hexdigest()
    return h[:24]


def _date_sort_key(date_str: str) -> str:
    """Best-effort sortable key (ISO) from a free-form date; '' sorts last."""
    if not date_str:
        return "9999-99-99"
    s = date_str.strip()
    # already ISO-ish
    import re
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # "12th February 2011" / "February 2011" / "2011"
    months = {m: i for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june", "july", "august",
         "september", "october", "november", "december"], 1)}
    y = re.search(r"\b(19|20)\d{2}\b", s)
    if not y:
        return "9999-99-99"
    year = y.group(0)
    mon = next((f"{months[name]:02d}" for name in months if name in s.lower()), "00")
    day = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", s)
    dd = f"{int(day.group(1)):02d}" if day and int(day.group(1)) <= 31 else "00"
    return f"{year}-{mon}-{dd}"


class EventTimeline:
    """Singleton DuckDB-backed store of structured document events."""

    _instance: Optional["EventTimeline"] = None
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
        EVENTS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            self._con = duckdb.connect(str(EVENTS_DB))
        except Exception as e:
            logger.error(f"[EventTimeline] init failed ({e}); in-memory fallback")
            self._con = duckdb.connect(":memory:")
        self._con.execute(
            "CREATE TABLE IF NOT EXISTS events ("
            "event_id VARCHAR PRIMARY KEY, doc_id VARCHAR, file_name VARCHAR, "
            "project VARCHAR, date VARCHAR, date_sort VARCHAR, event_type VARCHAR, "
            "actor VARCHAR, reason VARCHAR, severity VARCHAR, status VARCHAR, "
            "description VARCHAR, source VARCHAR)"
        )
        logger.info(f"[EventTimeline] Ready ({self.count()} events)")

    def count(self) -> int:
        return int(self._con.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    def add_events(self, rows: List[Dict]) -> int:
        """Insert event rows. Each: {doc_id, file_name, project?, date, event_type,
        actor?, reason?, severity?, status?, description}. Stable id dedupes re-runs."""
        if not rows:
            return 0
        with self._db_lock:
            before = self.count()
            for r in rows:
                etype = str(r.get("event_type", "")).strip().lower()
                desc = str(r.get("description", "")).strip()
                if etype not in EVENT_TYPES or not desc:
                    continue
                date = str(r.get("date", "")).strip()
                doc_id = str(r.get("doc_id", ""))
                eid = _event_id(doc_id, etype, date, desc)
                try:
                    self._con.execute(
                        "INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        [eid, doc_id, r.get("file_name", ""), r.get("project", ""),
                         date, _date_sort_key(date), etype, str(r.get("actor", "")),
                         str(r.get("reason", "")), str(r.get("severity", "")),
                         str(r.get("status", "")), desc, str(r.get("source", "enrichment"))],
                    )
                except Exception as e:
                    logger.debug(f"[EventTimeline] insert skipped: {e}")
            inserted = self.count() - before
        logger.info(f"[EventTimeline] +{inserted} events ({self.count()} total)")
        return inserted

    # ── Queries (deterministic — no LLM, no vector search) ────────────────
    def timeline(self, event_type: Optional[str] = None, actor: Optional[str] = None,
                 project: Optional[str] = None, limit: int = 200) -> List[Dict]:
        """Chronologically-ordered events, optionally filtered."""
        where, params = [], []
        if event_type:
            where.append("LOWER(event_type) = ?"); params.append(event_type.lower())
        if actor:
            where.append("LOWER(actor) LIKE ?"); params.append(f"%{actor.lower()}%")
        if project:
            where.append("project = ?"); params.append(project)
        sql = ("SELECT date, event_type, actor, reason, severity, status, description, "
               "file_name FROM events")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY date_sort LIMIT ?"
        params.append(limit)
        cols = ["date", "event_type", "actor", "reason", "severity", "status",
                "description", "file_name"]
        return [dict(zip(cols, row)) for row in self._con.execute(sql, params).fetchall()]

    def timeline_context(self, event_type: Optional[str] = None,
                         actor: Optional[str] = None, project: Optional[str] = None,
                         date_from: Optional[str] = None, date_to: Optional[str] = None,
                         limit: int = 60) -> List[Dict]:
        """Like timeline() but adds optional date-range filtering (on the sortable
        date_sort key) and returns doc_id too, so a synthesizer can cite evidence.
        Used by the live chronological query path. Date bounds are ISO 'YYYY-MM-DD'
        (or any prefix); free-form bounds are normalised through _date_sort_key."""
        where, params = [], []
        if event_type:
            where.append("LOWER(event_type) = ?"); params.append(event_type.lower())
        if actor:
            where.append("LOWER(actor) LIKE ?"); params.append(f"%{actor.lower()}%")
        if project:
            where.append("project = ?"); params.append(project)
        if date_from:
            where.append("date_sort >= ?"); params.append(_date_sort_key(date_from))
        if date_to:
            where.append("date_sort <= ?"); params.append(_date_sort_key(date_to))
        sql = ("SELECT date, event_type, actor, reason, severity, status, description, "
               "file_name, doc_id FROM events")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY date_sort LIMIT ?"
        params.append(limit)
        cols = ["date", "event_type", "actor", "reason", "severity", "status",
                "description", "file_name", "doc_id"]
        with self._db_lock:
            return [dict(zip(cols, row)) for row in self._con.execute(sql, params).fetchall()]

    def type_counts(self) -> Dict[str, int]:
        rows = self._con.execute(
            "SELECT event_type, COUNT(*) FROM events GROUP BY event_type ORDER BY 2 DESC"
        ).fetchall()
        return {r[0]: int(r[1]) for r in rows}

    def delete_by_document(self, doc_id: str, project_id: str = "") -> int:
        with self._db_lock:
            before = self.count()
            if project_id:
                self._con.execute(
                    "DELETE FROM events WHERE doc_id=? AND project=?", [doc_id, project_id]
                )
            else:
                self._con.execute("DELETE FROM events WHERE doc_id=?", [doc_id])
            return before - self.count()


_instance: Optional[EventTimeline] = None


def get_event_timeline() -> EventTimeline:
    global _instance
    if _instance is None:
        _instance = EventTimeline()
    return _instance
