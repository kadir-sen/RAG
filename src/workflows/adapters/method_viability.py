"""method_viability workflow — MVP.

Gathers which inputs are present and reports which delay-analysis methods the
available data can support. Screening only; the analyst selects the method.
"""

from __future__ import annotations

from typing import Any, List, Optional

from src.orchestration.helpers import md_block, table_block

from .. import caveats as CV
from ..blocks import finalize_blocks
from ..types import RESULT_PARTIAL, WorkflowId, WorkflowResult


def _corpus() -> str:
    try:
        from src.document_rag import _current_user_corpus
        return _current_user_corpus() or "demo"
    except Exception:
        return "demo"


def gather_availability(router: Any, corpus: str):
    from src.delay_reports.method_viability import Availability
    av = Availability()
    try:
        recs = router._programme_records() if router else []
        av.programme_updates = len(recs) >= 2
        from src.orchestration.resolver import resolve_xer
        av.baseline = bool(resolve_xer("baseline").resolved.get("baseline_xer")) \
            or len(recs) >= 1
    except Exception:
        pass
    try:
        from src.delay_reports import candidate_store
        av.confirmed_events = len(candidate_store.confirmed_events(corpus=corpus))
    except Exception:
        pass
    try:
        from src.delay_reports import notice_matrix as nm
        av.notices = len(nm.enumerate_served_notices(corpus=corpus))
    except Exception:
        pass
    try:
        from src.delay_reports import contract_mechanism as cm
        av.contract_mechanisms = len(
            cm.get_contract_mechanisms(corpus=corpus).mechanisms)
    except Exception:
        pass
    return av


def run(query: str, router: Any, doc_ids: Optional[List[str]] = None
        ) -> WorkflowResult:
    wid = WorkflowId.METHOD_VIABILITY
    from src.delay_reports import method_viability as mv

    av = gather_availability(router, _corpus())
    rows_data = mv.assess(av)

    rows = [[r["method"], "Yes" if r["viable"] else "No", r["requires"]]
            for r in rows_data]
    table = {"title": "Delay-analysis method viability (data-availability screen)",
             "columns": ["Method", "Data available", "Requires"], "rows": rows}

    inputs = (f"Inputs found — baseline: {'yes' if av.baseline else 'no'}, "
              f"programme updates: {'yes' if av.programme_updates else 'no'}, "
              f"confirmed events: {av.confirmed_events}, notices: {av.notices}, "
              f"contract mechanisms: {av.contract_mechanisms}.")
    viable = [r["method"] for r in rows_data if r["viable"]]
    lead = (f"{inputs}\n\nMethods supportable by the available data: "
            + (", ".join(viable) if viable else "none yet — upload/confirm the "
               "missing inputs.") + ".")

    blocks = [md_block(lead, "summary"), table_block(table, "methods")]
    caveats = list(mv.STANDING_CAVEATS) + [CV.ANALYST_REVIEW_ENTITLEMENT]
    blocks = finalize_blocks(blocks, {"availability_screen": "passed"}, True, [],
                             caveats)
    return WorkflowResult(
        workflow_id=wid, status=RESULT_PARTIAL, blocks=blocks, answer=lead,
        caveats=caveats, analyst_review_required=True,
        validation={"availability_screen": "passed"})
