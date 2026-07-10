"""contract_mechanism_summary workflow — MVP.

Extracts the notice / EOT / claim time-bar mechanisms stated in the contract
document(s) so an analyst can see the governing periods (and the matrix can use
clause-derived periods). Extraction only; not legal advice.
"""

from __future__ import annotations

from typing import Any, List, Optional

from src.orchestration.helpers import md_block, table_block

from .. import caveats as CV
from ..blocks import finalize_blocks
from ..types import (
    RESULT_PARTIAL, RESULT_UNAVAILABLE, WorkflowId, WorkflowResult,
)


def _corpus() -> str:
    try:
        from src.document_rag import _current_user_corpus
        return _current_user_corpus() or "demo"
    except Exception:
        return "demo"


def run(query: str, router: Any, doc_ids: Optional[List[str]] = None
        ) -> WorkflowResult:
    wid = WorkflowId.CONTRACT_MECHANISM_SUMMARY
    from src.delay_reports import contract_mechanism as cm

    res = cm.get_contract_mechanisms(corpus=_corpus(), doc_ids=doc_ids)

    if not res.mechanisms:
        text = ("No contractual notice/EOT periods could be extracted. Upload "
                "the conditions of contract (classified as a contract document) "
                "so the notice periods can be read from it.")
        return WorkflowResult(
            workflow_id=wid, status=RESULT_UNAVAILABLE, answer=text,
            blocks=[md_block(text, "none")],
            substitute=WorkflowId.DELAY_EVENT_CANDIDATE_REGISTER.value)

    rows = [[m.clause_ref or "—", m.mechanism_type, f"{m.period_days} days",
             m.basis or "—", m.confidence,
             f"{m.file_name}, p.{m.page_number}", m.quote[:120]]
            for m in sorted(res.mechanisms, key=lambda x: (-x.period_days))]
    table = {"title": "Contract notice / EOT mechanisms (extracted — verify "
                      "against the executed contract)",
             "columns": ["Clause", "Type", "Period", "Basis", "Confidence",
                         "Source", "Quote"],
             "rows": rows}

    lead = (f"Extracted {len(rows)} notice/EOT/claim period(s) from "
            f"{res.contract_docs} contract document(s). These are read from the "
            "contract text and must be verified before use.")
    blocks = [md_block(lead, "summary"), table_block(table, "mechanisms")]
    caveats = list(res.caveats) + [CV.ANALYST_REVIEW_ENTITLEMENT]
    blocks = finalize_blocks(blocks, {"extraction_guard": "passed"}, True, [],
                             caveats)
    return WorkflowResult(
        workflow_id=wid, status=RESULT_PARTIAL, blocks=blocks, answer=lead,
        caveats=caveats, analyst_review_required=True,
        validation={"extraction_guard": "passed"})
