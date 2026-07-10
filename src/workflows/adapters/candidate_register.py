"""delay_event_candidate_register workflow.

Surfaces a data-first, containment-validated register of *candidate* delay
events for a topic: retrieve evidence → LLM extraction under the deterministic
containment guard (date + actor/quote must appear verbatim in the snippet — the
LLM cannot invent an event) → persist as candidates for analyst confirm/reject/
merge. Every row carries source (file/page), date and a verbatim quote. Nothing
here is a finding: candidates require analyst confirmation before any claim use.
"""

from __future__ import annotations

from typing import Any, List, Optional

from src.orchestration.helpers import md_block, table_block

from .. import caveats as CV
from ..blocks import finalize_blocks
from ..types import (
    RESULT_CLARIFICATION, RESULT_PARTIAL, RESULT_SUCCESS,
    WorkflowId, WorkflowResult,
)


def run(query: str, router: Any, doc_ids: Optional[List[str]] = None
        ) -> WorkflowResult:
    wid = WorkflowId.DELAY_EVENT_CANDIDATE_REGISTER
    from src.delay_reports.scope import resolve_event_scope
    from src.delay_reports.retrieval import retrieve_evidence
    from src.delay_reports.register import build_event_register
    from src.delay_reports import candidate_store

    scope = resolve_event_scope(query, router)
    if scope.needs_clarification:
        return WorkflowResult(
            workflow_id=wid, status=RESULT_CLARIFICATION,
            answer=scope.clarification,
            blocks=[{"type": "clarification", "block_id": "clarify",
                     "question": scope.clarification or "Which delay event "
                     "should I build the candidate register for?",
                     "options": []}])

    corpus = ""
    try:
        from src.document_rag import _current_user_corpus
        corpus = _current_user_corpus() or "demo"
    except Exception:
        corpus = "demo"

    evidence = retrieve_evidence(scope, corpus, doc_ids)
    if not evidence:
        return WorkflowResult(
            workflow_id=wid, status=RESULT_CLARIFICATION,
            answer="No delay-related correspondence was found. Upload the "
                   "relevant notices/letters or name a specific delay event.",
            blocks=[{"type": "clarification", "block_id": "clarify",
                     "question": "No evidence found — name a specific delay "
                     "event or upload the correspondence.", "options": []}])

    register = build_event_register(evidence, scope.event_title or "delay events")
    persisted = candidate_store.add_candidates(
        register.entries, corpus=corpus, topic=scope.event_title or "")

    rows = [[e.event_date, e.actor, (e.issue or "")[:110],
             f"{e.file_name}, p.{e.page_number}", e.support_level, "candidate"]
            for e in sorted(register.entries, key=lambda e: e.event_date)]
    table = {"title": "Candidate delay events (as stated in the record — "
                      "await analyst confirmation, not findings)",
             "columns": ["Date", "Party", "Stated issue", "Source", "Support",
                         "Status"],
             "rows": rows}

    lead = (f"Found {len(rows)} candidate delay event(s) for "
            f"'{scope.event_title or 'delay events'}'. Each is validated for "
            "evidence containment (date + actor/quote appear verbatim in the "
            "source) but is NOT a finding — confirm/reject/merge before use.")
    blocks: List[dict] = [md_block(lead, "summary")]
    if rows:
        blocks.append(table_block(table, "candidates"))

    caveats = list(register.caveats)
    caveats.append("Candidate events are contemporaneous statements in the "
                   "record, not causation or liability findings.")
    caveats.append(CV.ANALYST_REVIEW_ENTITLEMENT)
    if register.llm_failures:
        caveats.append(CV.LLM_NARRATIVE_UNAVAILABLE)
    if not rows:
        caveats.append("No dated events passed evidence-containment validation; "
                       "analyst review of the source documents is recommended.")

    guards = {"containment_guard": "passed"}
    blocks = finalize_blocks(blocks, guards, True, [], caveats)
    status = RESULT_SUCCESS if rows and not register.llm_failures \
        else RESULT_PARTIAL
    return WorkflowResult(
        workflow_id=wid, status=status, blocks=blocks, answer=lead,
        caveats=caveats, analyst_review_required=True, validation=guards,
        debug_trace={"persisted": persisted, "evidence": len(evidence)})
