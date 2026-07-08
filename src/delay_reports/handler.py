"""Orchestrator: user-defined delay-event chronology section.

scope → evidence → LLM register (containment-guarded) → chronology table →
narrative (guard, max-1 rewrite, deterministic fallback) → ToolResult with
validation audit trail + clickable sources + optional Programme Support +
events.db write-back. Never raises to the router.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from .chronology import TABLE_COLUMNS, build_chronology_table, table_as_tool_rows
from .guard import chronology_guard
from .narrative import deterministic_fallback, draft_event_narrative
from .register import build_event_register
from .retrieval import retrieve_evidence
from .schemas import (
    STATUS_COMPLETE, STATUS_PARTIAL, ChronologyTable, RegisterResult,
    ScopeResult, ToolResult, json_safe,
)
from .scope import resolve_event_scope

logger = logging.getLogger(__name__)

TOOL_ID = "delay_reports.event_chronology"

_XER_SUPPORT_RE = re.compile(r"\bprogramme\b|\bxer\b|schedule support", re.IGNORECASE)


def _report(kind: str, label: str, detail: str = "") -> None:
    try:
        from backend.tasks.query_progress import report_step
        report_step(kind, label, detail)
    except Exception:
        pass


def _clarification(message: str) -> Dict[str, Any]:
    return {"answer": message, "query_type": "delay_report",
            "clarification": True, "sources": []}


def _current_corpus() -> str:
    try:
        from src.document_rag import _current_user_corpus
        return (_current_user_corpus() or "demo").lower()
    except Exception:
        return "demo"


def run_event_chronology(query: str, router: Any = None,
                         doc_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Entry point called from QueryRouter._dispatch_query."""
    current_q = query
    try:
        if router is not None:
            current_q = router._current_question(query)
    except Exception:
        pass

    # 1. Scope
    scope = resolve_event_scope(current_q, router)
    if scope.needs_clarification:
        return _clarification(scope.clarification)
    title = scope.event_title

    # 2. Evidence
    _report("searching", f"Collecting correspondence evidence for '{title}'...")
    corpus = _current_corpus()
    evidence = retrieve_evidence(scope, corpus, doc_ids)
    if not evidence:
        return _clarification(
            f"No documents in the corpus mention '{title}'. Please check the "
            "event name or upload the relevant correspondence."
        )

    # 3. Register (LLM extraction + deterministic containment validation)
    _report("analysing", f"Extracting dated events from {len(evidence)} evidence items...")
    register = build_event_register(evidence, title)
    if not register.entries:
        if register.llm_failures:
            summary = (f"The chronology for '{title}' could not be built "
                       "right now — the extraction service is temporarily "
                       "unavailable. Please try again shortly.")
        else:
            summary = (f"No dated events for '{title}' passed evidence "
                       "validation.")
        result = ToolResult(
            tool_id=TOOL_ID, status="failed",
            summary=summary,
            warnings=[f"{len(evidence)} evidence item(s) were reviewed but no "
                      "extracted event survived the date/actor/quote "
                      "containment checks."] if not register.llm_failures else
                     [f"{register.llm_failures} extraction batch(es) failed "
                      "due to a temporary LLM service error."],
            caveats=register.caveats,
            requires_analyst_review=True,
            raw={"unresolved": json_safe(register.unresolved)},
        )
        result.validation["computation_guard"] = {
            "pre": "passed", "post": "violations",
            "violations": ["no validated register entries"]}
        return {"answer": result.summary, "query_type": "delay_report",
                "programme_artifact": result.to_dict(), "sources": []}

    # 4. Chronology table
    table = build_chronology_table(register)

    # 5. ToolResult skeleton (guard needs it for grounding context)
    tables = [{
        "title": f"Chronology — {title}",
        "columns": TABLE_COLUMNS,
        "rows": table_as_tool_rows(table),
    }]
    if register.unresolved:
        tables.append({
            "title": "Excluded items — failed evidence containment checks; "
                     "analyst review required",
            "columns": ["Evidence", "File", "Reason"],
            "rows": [[u.get("evidence_id", "—"), u.get("file_name", "—"),
                      u.get("reason", "")] for u in register.unresolved[:20]],
        })
    caveats = list(table.caveats)
    caveats.append(
        "Statements are reproduced as the parties' claims as recorded in "
        "correspondence; they are not independently verified facts."
    )
    result = ToolResult(
        tool_id=TOOL_ID,
        status=STATUS_COMPLETE,
        summary=(f"Chronology for '{title}': {len(table.rows)} dated "
                 f"paragraph(s) from {len({r.entry.file_name for r in table.rows})} "
                 "document(s)."),
        tables=tables,
        caveats=caveats,
        requires_analyst_review=bool(register.unresolved),
        raw={"register": json_safe(register.entries),
             "unresolved_count": len(register.unresolved)},
    )
    result.validation["computation_guard"] = {
        "pre": "passed",
        "post": "passed" if not register.unresolved else "violations",
        "violations": [u.get("reason", "") for u in register.unresolved[:5]],
    }

    # 6. Optional Programme Support (opt-in only; never causation)
    _maybe_programme_support(current_q, router, result)

    # 7. Narrative + guard (max-1 rewrite → deterministic fallback)
    _report("analysing", "Drafting the chronology narrative...")
    answer = _guarded_narrative(table, scope, result, title)

    # 8. events.db write-back — side benefit, never blocks
    _write_back_events(register, title)

    # Plain (untyped) sources map to Citations in the response builder —
    # clickable page-anchored refs matching the "(file, p.N)" paragraph refs.
    sources = [{
        "file_name": r.entry.file_name,
        "doc_id": r.entry.doc_id or r.entry.file_name,
        "page_number": r.entry.page_number,
        "text_snippet": r.entry.quote[:300],
        "date": r.date,
    } for r in table.rows]

    return {"answer": answer, "query_type": "delay_report",
            "programme_artifact": result.to_dict(), "sources": sources}


def _guarded_narrative(table: ChronologyTable, scope: ScopeResult,
                       result: ToolResult, title: str) -> str:
    def _audit(status: str, violations=None) -> None:
        result.validation["narrative_guard"] = {
            "status": status, "violations": list(violations or [])}

    last_violations: list = []
    try:
        narrative = draft_event_narrative(table, title)
        verdict = chronology_guard(narrative, table, scope, result)
        if verdict.approved:
            _audit("approved")
            return narrative
        last_violations = verdict.violations
        logger.info(f"[DelayReports] guard rejected: {verdict.violations[:4]}")
        retry = draft_event_narrative(
            table, title,
            rewrite_note="\n".join(f"- {v}" for v in verdict.violations[:8]))
        verdict2 = chronology_guard(retry, table, scope, result)
        if verdict2.approved:
            _audit("rewritten_then_approved")
            return retry
        last_violations = verdict2.violations
        _audit("fallback_after_rejection", last_violations)
    except Exception as e:
        logger.warning(f"[DelayReports] narrative failed open: {e}")
        _audit("llm_unavailable")
        return ("_Automated narrative is temporarily unavailable; showing the "
                "validated chronology only._\n\n"
                + deterministic_fallback(table, title))
    return ("_Automated narrative failed validation; showing the validated "
            "chronology only._\n\n" + deterministic_fallback(table, title))


def _maybe_programme_support(query: str, router: Any,
                             result: ToolResult) -> None:
    """Opt-in XER support subsection. Indicates movement; never causation."""
    if not _XER_SUPPORT_RE.search(query or "") or router is None:
        return
    try:
        records = router._programme_records()
        if not records:
            return
        from src.programme_tools import run_tool
        tool_id = ("programme.milestone_shift" if len(records) >= 2
                   else "programme.inventory")
        _report("tool", "Adding programme support subsection...")
        support = run_tool(tool_id, records)
        if support.status == "failed":
            return
        for t in support.tables[:1]:
            result.tables.append({**t, "title": f"Programme Support — {t['title']}"})
        result.caveats.append(
            "Programme Support data indicates schedule movement only; it does "
            "not establish causation for this delay event."
        )
    except Exception as e:
        logger.debug(f"[DelayReports] programme support skipped: {e}")


def _write_back_events(register: RegisterResult, title: str) -> None:
    try:
        from src.event_timeline import get_event_timeline
        # event_type must be in event_timeline.EVENT_TYPES — chronology
        # entries are delay events by construction.
        rows = [{
            "doc_id": e.doc_id, "file_name": e.file_name, "project": "",
            "date": e.event_date, "event_type": "delay",
            "actor": e.actor, "reason": e.issue, "severity": "",
            "status": "", "description": e.quote,
            "source": "delay_chronology",
        } for e in register.entries]
        if rows:
            get_event_timeline().add_events(rows)
    except Exception as e:
        logger.debug(f"[DelayReports] events.db write-back skipped: {e}")
