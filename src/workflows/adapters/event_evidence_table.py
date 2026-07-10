"""event_evidence_table workflow.

Builds an evidence table from ANALYST-CONFIRMED delay events (the candidate
store), never from raw retrieval — so it only ever shows evidence an analyst
has already accepted. No confirmed events → a helpful pointer to the register.
Nothing here is a finding: an evidence table supports a chronology, it does not
establish liability.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional

from src.orchestration.helpers import md_block, table_block

from .. import caveats as CV
from ..blocks import finalize_blocks
from ..types import (
    RESULT_CLARIFICATION, RESULT_SUCCESS, RESULT_UNAVAILABLE,
    WorkflowId, WorkflowResult,
)

_EVENT_NO = re.compile(r"\bevent\s*(?:no\.?|number|#)?\s*(\d{1,3})\b", re.I)


def _corpus() -> str:
    try:
        from src.document_rag import _current_user_corpus
        return _current_user_corpus() or "demo"
    except Exception:
        return "demo"


def run(query: str, router: Any, doc_ids: Optional[List[str]] = None
        ) -> WorkflowResult:
    wid = WorkflowId.EVENT_EVIDENCE_TABLE
    from src.delay_reports import candidate_store

    corpus = _corpus()
    confirmed = candidate_store.confirmed_events(corpus=corpus)

    # No confirmed events → helpful pointer (not an error, not a clarification).
    if not confirmed:
        msg = ("No confirmed delay events yet. First run the *candidate delay "
               "event register*, then confirm the events you want — the "
               "evidence table is built from confirmed events only.")
        return WorkflowResult(
            workflow_id=wid, status=RESULT_UNAVAILABLE, answer=msg,
            blocks=[md_block(msg, "no_confirmed")],
            substitute=WorkflowId.DELAY_EVENT_CANDIDATE_REGISTER.value)

    ordered = sorted(confirmed, key=lambda c: c.get("event_date") or "")

    # Resolve which event: "Event NN" (1-indexed) or a topic phrase.
    selected = None
    m = _EVENT_NO.search(query or "")
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(ordered):
            selected = ordered[idx]
        else:
            return _clarify(wid, f"There is no Event {m.group(1)}; "
                            f"{len(ordered)} confirmed event(s) exist.")
    else:
        ql = (query or "").lower()
        topic_hits = [c for c in ordered
                      if c.get("topic") and c["topic"].lower() in ql]
        if len(topic_hits) == 1:
            selected = topic_hits[0]
        elif len(ordered) == 1:
            selected = ordered[0]

    # Multiple confirmed events and none picked → show the list, ask to select.
    if selected is None:
        rows = [[i + 1, c.get("event_date", ""), c.get("actor", ""),
                 (c.get("issue") or "")[:80],
                 f"{c.get('file_name', '')}, p.{c.get('page_number', '')}"]
                for i, c in enumerate(ordered)]
        table = {"title": "Confirmed delay events",
                 "columns": ["#", "Date", "Party", "Issue", "Source"],
                 "rows": rows}
        blocks = [md_block(f"{len(ordered)} confirmed delay event(s). Which "
                           "event's evidence? e.g. \"evidence for Event 01\".",
                           "pick"), table_block(table, "events")]
        blocks = finalize_blocks(blocks, {"selection_guard": "passed"}, True, [],
                                 [CV.ANALYST_REVIEW_ENTITLEMENT])
        return WorkflowResult(workflow_id=wid, status=RESULT_CLARIFICATION,
                              answer="Which confirmed event?", blocks=blocks)

    # Evidence table for the selected event.
    row = [[selected.get("file_name", ""), selected.get("event_date", ""),
            selected.get("actor", ""), selected.get("page_number", ""),
            (selected.get("quote") or "")[:200], selected.get("support_level", ""),
            f"{selected.get('file_name', '')}, p.{selected.get('page_number', '')}"]]
    table = {"title": f"Evidence — {selected.get('topic') or 'confirmed event'} "
                      f"({selected.get('event_date', '')})",
             "columns": ["Document", "Date", "Party", "Page", "Snippet",
                         "Support", "Citation"],
             "rows": row}
    lead = (f"Evidence for the confirmed event dated "
            f"{selected.get('event_date', '')} ({selected.get('actor', '')}).")
    blocks = [md_block(lead, "summary"), table_block(table, "evidence")]
    caveats = ["An evidence table supports a chronology; it does not establish "
               "final liability or entitlement.", CV.ANALYST_REVIEW_ENTITLEMENT]
    blocks = finalize_blocks(blocks, {"containment_guard": "passed"}, True, [],
                             caveats)
    return WorkflowResult(
        workflow_id=wid, status=RESULT_SUCCESS, blocks=blocks, answer=lead,
        caveats=caveats, analyst_review_required=True,
        validation={"containment_guard": "passed"})


def _clarify(wid, question: str) -> WorkflowResult:
    return WorkflowResult(
        workflow_id=wid, status=RESULT_CLARIFICATION, answer=question,
        blocks=[{"type": "clarification", "block_id": "clarify",
                 "question": question, "options": []}])
