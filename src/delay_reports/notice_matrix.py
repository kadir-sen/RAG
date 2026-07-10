"""Notice compliance matrix — MVP engine (deterministic).

For each ANALYST-CONFIRMED delay event, check whether a contractual notice was
served in time. The "served" side is real (enumerated from the notice store);
the "required period" side is a **configurable assumption**, NOT extracted from
the executed contract — Sprint 3B (contract mechanism extraction) will replace
the assumed periods with clause-derived ones. Until then every row is labelled
"assumed", correlation is heuristic, and the whole matrix is a preliminary,
analyst-review-required screening — never a determination of entitlement,
waiver, or liability.

No LLM: dates + a config table + a date-window correlation. Never raises.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Assumed required-notice periods (days after the event) by event topic keyword.
# These are DEFAULTS for screening only — a FIDIC-1999 Sub-Clause 20.1 style
# 28-day baseline — not the parties' actual contract. Overridable per run.
DEFAULT_NOTICE_RULES: Dict[str, int] = {
    "default": 28,
    "delay": 28,
    "variation": 14,
    "instruction": 14,
    "extension of time": 28,
    "eot": 28,
}

STATUS_IN_TIME = "in_time"
STATUS_LATE = "late"
STATUS_NOT_SERVED = "not_served"
STATUS_UNKNOWN = "unknown_date"


@dataclass
class MatrixRow:
    event_topic: str
    event_date: str
    actor: str
    required_days: int
    deadline: str
    notice_served: bool
    served_date: Optional[str]
    served_ref: str
    status: str
    gap_days: Optional[int]        # served_date - deadline (negative = early)


@dataclass
class NoticeMatrix:
    rows: List[MatrixRow] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)
    notice_count: int = 0


def _iso(d: str) -> Optional[datetime]:
    try:
        return datetime.strptime((d or "")[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _required_days(topic: str, rules: Dict[str, int]) -> int:
    t = (topic or "").lower()
    for key, days in rules.items():
        if key != "default" and key in t:
            return days
    return rules.get("default", 28)


def enumerate_served_notices(corpus: str = "",
                             project_id: Optional[str] = None
                             ) -> List[Dict[str, Any]]:
    """Served notices for the corpus (date/sender/subject/ref). Best-effort over
    the catalog's notice_summary; empty list if none. Never raises."""
    out: List[Dict[str, Any]] = []
    try:
        from src.catalog import get_catalog
        for e in get_catalog().get_entries_with_notices():
            if corpus and getattr(e, "corpus", "") not in ("", corpus):
                continue
            ns = getattr(e, "notice_summary", None) or {}
            actions = " ".join(str(a) for a in (ns.get("actions") or []))
            dtype = str(ns.get("doc_type", "")).lower()
            # keep delay/notice-ish correspondence only
            if not ("notice" in dtype or "delay" in dtype
                    or "notif" in actions.lower() or "delay" in actions.lower()):
                continue
            out.append({
                "date": ns.get("date", ""),
                "sender": ns.get("sender", ""),
                "subject": ns.get("subject", ""),
                "doc_id": getattr(e, "file_hash", "") or ns.get("doc_id", ""),
                "file_name": getattr(e, "source_file", "") or ns.get("file_name", ""),
                "topics": " ".join(str(t) for t in (ns.get("key_topics") or [])),
            })
    except Exception as e:
        logger.debug(f"[NoticeMatrix] notice enumeration degraded: {e}")
    return out


def _match_notice(event: Dict[str, Any], notices: List[Dict[str, Any]],
                  deadline: Optional[datetime]) -> Optional[Dict[str, Any]]:
    """Heuristic correlation: a notice served on/after the event, closest to the
    event, with a light topic/actor overlap. Analyst must verify."""
    ev_date = _iso(event.get("event_date", ""))
    if ev_date is None:
        return None
    topic = (event.get("topic") or event.get("issue") or "").lower()
    actor = (event.get("actor") or "").lower()
    ev_terms = {w for w in topic.split() if len(w) >= 4}
    best = None
    best_gap = None
    for n in notices:
        nd = _iso(n.get("date", ""))
        if nd is None or nd < ev_date - timedelta(days=3):
            continue  # served before the event (minus a small grace) → not this
        hay = f"{n.get('subject','')} {n.get('topics','')}".lower()
        overlap = bool(ev_terms & {w for w in hay.split() if len(w) >= 4})
        actor_hit = bool(actor) and actor.split()[0] in n.get("sender", "").lower()
        if not (overlap or actor_hit):
            continue
        gap = abs((nd - ev_date).days)
        if best_gap is None or gap < best_gap:
            best, best_gap = n, gap
    return best


def build_matrix(confirmed_events: List[Dict[str, Any]],
                 notices: List[Dict[str, Any]],
                 rules: Optional[Dict[str, int]] = None) -> NoticeMatrix:
    """Compare each confirmed event's served notice against the assumed period."""
    rules = rules or DEFAULT_NOTICE_RULES
    m = NoticeMatrix(notice_count=len(notices))
    for ev in confirmed_events:
        topic = ev.get("topic") or ev.get("issue") or "delay event"
        ev_dt = _iso(ev.get("event_date", ""))
        req = _required_days(topic, rules)
        if ev_dt is None:
            m.rows.append(MatrixRow(topic, ev.get("event_date", ""),
                                    ev.get("actor", ""), req, "", False, None,
                                    "", STATUS_UNKNOWN, None))
            continue
        deadline = ev_dt + timedelta(days=req)
        match = _match_notice(ev, notices, deadline)
        if match is None:
            status, served_date, ref, gap = STATUS_NOT_SERVED, None, "", None
        else:
            served_date = (match.get("date") or "")[:10]
            sd = _iso(served_date)
            ref = match.get("file_name", "") or match.get("doc_id", "")
            gap = (sd - deadline).days if sd else None
            status = STATUS_IN_TIME if (sd and sd <= deadline) else STATUS_LATE
        m.rows.append(MatrixRow(
            topic, ev.get("event_date", ""), ev.get("actor", ""), req,
            deadline.strftime("%Y-%m-%d"), match is not None, served_date, ref,
            status, gap))

    m.caveats = [
        "Required notice periods are ASSUMED screening defaults (FIDIC-1999 "
        "Sub-Clause 20.1 style: 28 days), NOT read from the executed contract — "
        "confirm each against the actual conditions of contract.",
        "Event↔notice correlation is heuristic (date window + topic/actor match) "
        "and must be verified by an analyst.",
        "This is a preliminary compliance screening, not a determination of "
        "entitlement, time-bar, waiver or liability.",
    ]
    if not notices:
        m.caveats.insert(0, "No delay-notice correspondence was found in the "
                         "corpus; every event is shown as 'not served' pending "
                         "the relevant notices being uploaded.")
    return m
