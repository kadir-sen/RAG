"""notice_compliance_matrix workflow — MVP.

Requires analyst-confirmed delay events (prerequisite). For each, checks whether
a contractual notice was served within an ASSUMED period (see notice_matrix
engine). Not a legal finding: the required periods are assumed defaults, the
event↔notice link is heuristic, and analyst review is mandatory.
"""

from __future__ import annotations

from typing import Any, List, Optional

from src.orchestration.helpers import md_block, table_block

from .. import caveats as CV
from ..blocks import finalize_blocks
from ..types import (
    RESULT_PARTIAL, RESULT_UNAVAILABLE, WorkflowId, WorkflowResult,
)

_STATUS_LABEL = {
    "in_time": "Served (in time)", "late": "Served (late)",
    "not_served": "No notice found", "unknown_date": "Event date unknown",
}


def _corpus() -> str:
    try:
        from src.document_rag import _current_user_corpus
        return _current_user_corpus() or "demo"
    except Exception:
        return "demo"


def run(query: str, router: Any, doc_ids: Optional[List[str]] = None
        ) -> WorkflowResult:
    wid = WorkflowId.NOTICE_COMPLIANCE_MATRIX
    from src.delay_reports import candidate_store, notice_matrix as nm

    corpus = _corpus()
    confirmed = candidate_store.confirmed_events(corpus=corpus)

    # Prerequisite: no confirmed events → point at the register (not an error).
    if not confirmed:
        text = ("**Notice compliance matrix** requires **confirmed delay "
                "events**. Run the *candidate delay event register*, confirm "
                "the relevant events, then ask for the matrix.")
        return WorkflowResult(
            workflow_id=wid, status=RESULT_UNAVAILABLE, answer=text,
            blocks=[md_block(text, "prereq")],
            substitute=WorkflowId.DELAY_EVENT_CANDIDATE_REGISTER.value)

    notices = nm.enumerate_served_notices(corpus=corpus)

    # Prefer CLAUSE-DERIVED periods from the contract; fall back to assumed.
    rules = None
    clause_derived = False
    try:
        from src.delay_reports import contract_mechanism as cm
        mechs = cm.get_contract_mechanisms(corpus=corpus).mechanisms
        derived = cm.notice_rules_from_mechanisms(mechs)
        if derived:
            rules = {**nm.DEFAULT_NOTICE_RULES, **derived}
            clause_derived = True
    except Exception:
        rules = None
    matrix = nm.build_matrix(confirmed, notices, rules)
    if clause_derived:
        matrix.caveats = [
            "Required notice periods are CLAUSE-DERIVED from the contract "
            "document but must still be verified against the executed contract "
            "(amendments/cross-references)."] + [
            c for c in matrix.caveats if "assumed" not in c.lower()]

    req_basis = "clause" if clause_derived else "assumed"
    rows = [[r.event_topic[:40], r.event_date,
             f"{r.required_days}d ({req_basis})",
             r.deadline, _STATUS_LABEL.get(r.status, r.status),
             r.served_date or "—",
             ("+%dd" % r.gap_days if r.gap_days and r.gap_days > 0
              else ("%dd" % r.gap_days if r.gap_days is not None else "—")),
             r.served_ref or "—"]
            for r in matrix.rows]
    table = {"title": "Notice compliance matrix (preliminary — assumed periods)",
             "columns": ["Delay event", "Event date", "Required notice",
                         "Deadline", "Status", "Served", "Vs deadline",
                         "Notice ref"],
             "rows": rows}

    late = sum(1 for r in matrix.rows if r.status == "late")
    missing = sum(1 for r in matrix.rows if r.status == "not_served")
    lead = (f"Preliminary notice-compliance screening for {len(matrix.rows)} "
            f"confirmed delay event(s): {late} late, {missing} with no notice "
            f"found ({matrix.notice_count} notice(s) in the corpus). Assumed "
            "periods — verify against the contract.")

    blocks = [md_block(lead, "summary"), table_block(table, "matrix")]
    caveats = list(matrix.caveats) + [CV.ANALYST_REVIEW_ENTITLEMENT]
    blocks = finalize_blocks(blocks, {"notice_rules": "assumed"}, True, [],
                             caveats)
    return WorkflowResult(
        workflow_id=wid, status=RESULT_PARTIAL, blocks=blocks, answer=lead,
        caveats=caveats, analyst_review_required=True,
        validation={"notice_rules": "assumed"})
