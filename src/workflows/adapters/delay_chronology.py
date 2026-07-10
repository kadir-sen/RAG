"""delay_chronology_section (plain 6.1) — wraps run_event_chronology.

The HTML-rendered variant is handled by delegating to the existing
composite.chronology_html runner (executor mode="html"); this adapter produces
the plain markdown 6.1 section + chronology table.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional

from src.orchestration.helpers import md_block, table_block, tool_result_guard_statuses

from .. import caveats as CV
from ..blocks import finalize_blocks
from ..types import (
    RESULT_CLARIFICATION, RESULT_PARTIAL, RESULT_SUCCESS,
    WorkflowId, WorkflowResult,
)

_CONFIRMED_RE = re.compile(r"\bconfirmed\b", re.IGNORECASE)
_EVENT_NO = re.compile(r"\bevent\s*(?:no\.?|number|#)?\s*(\d{1,3})\b", re.I)


def _confirmed_scope(query: str) -> Optional[dict]:
    """If the query targets a CONFIRMED event, resolve it → derived query +
    doc_ids (prioritising the confirmed evidence). Returns a dict or a
    clarification marker; None means 'not a confirmed-event request'."""
    if not _CONFIRMED_RE.search(query or ""):
        return None
    try:
        from src.document_rag import _current_user_corpus
        corpus = _current_user_corpus() or "demo"
    except Exception:
        corpus = "demo"
    try:
        from src.delay_reports import candidate_store
        confirmed = candidate_store.confirmed_events(corpus=corpus)
    except Exception:
        confirmed = []
    if not confirmed:
        return {"clarification": "No confirmed delay events yet. Run the "
                "candidate delay event register and confirm an event first, "
                "then ask for its chronology."}
    ordered = sorted(confirmed, key=lambda c: c.get("event_date") or "")
    m = _EVENT_NO.search(query or "")
    picked = None
    if m and 0 <= int(m.group(1)) - 1 < len(ordered):
        picked = ordered[int(m.group(1)) - 1]
    else:
        ql = (query or "").lower()
        hits = [c for c in ordered if c.get("topic") and c["topic"].lower() in ql]
        picked = hits[0] if len(hits) == 1 else (ordered[0]
                                                 if len(ordered) == 1 else None)
    if picked is None:
        return {"clarification": f"{len(ordered)} confirmed events exist — "
                "which one? e.g. 'chronology for confirmed Event 01'."}
    title = picked.get("topic") or picked.get("issue") or "confirmed delay event"
    doc = picked.get("doc_id")
    return {"query": f"Prepare a 6.1 chronology for {title}",
            "doc_ids": [doc] if doc else None}


def run(query: str, router: Any, doc_ids: Optional[List[str]] = None
        ) -> WorkflowResult:
    wid = WorkflowId.DELAY_CHRONOLOGY_SECTION

    # Confirmed-event path: derive scope + prioritise confirmed evidence docs.
    scope = _confirmed_scope(query)
    if scope and scope.get("clarification"):
        return WorkflowResult(
            workflow_id=wid, status=RESULT_CLARIFICATION,
            answer=scope["clarification"],
            blocks=[{"type": "clarification", "block_id": "clarify",
                     "question": scope["clarification"], "options": []}])
    if scope:
        query = scope["query"]
        doc_ids = scope.get("doc_ids") or doc_ids

    from src.delay_reports import run_event_chronology
    out = run_event_chronology(query, router, doc_ids)

    if out.get("clarification"):
        return WorkflowResult(
            workflow_id=wid, status=RESULT_CLARIFICATION,
            answer=out.get("answer", ""),
            blocks=[{"type": "clarification", "block_id": "clarify",
                     "question": out.get("answer", "Please name the delay "
                                 "event."), "options": []}],
        )

    tr = out.get("programme_artifact") or {}
    blocks: List[dict] = [md_block(out.get("answer", ""), "narrative")]
    for i, t in enumerate((tr.get("tables") or [])[:2]):
        blocks.append(table_block(t, f"table{i + 1}"))

    guards = tool_result_guard_statuses(tr)
    analyst = bool(tr.get("requires_analyst_review", True))
    caveats = list(tr.get("caveats") or [])
    caveats.append(CV.CHRONOLOGY_PRELIMINARY)
    caveats.append(CV.ANALYST_REVIEW_ENTITLEMENT)
    blocks = finalize_blocks(blocks, guards, analyst, [], caveats,
                             tr.get("warnings"))
    status = RESULT_PARTIAL if analyst else RESULT_SUCCESS
    return WorkflowResult(
        workflow_id=wid, status=status, blocks=blocks,
        answer=out.get("answer", "Delay chronology section:"), caveats=caveats,
        sources=out.get("sources") or [], primary_artifact=tr,
        analyst_review_required=analyst, validation=guards,
    )
