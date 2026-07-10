"""programme_inventory workflow — wraps programme.inventory (no composite)."""

from __future__ import annotations

from typing import Any, List, Optional

from src.orchestration.helpers import (
    artifact_blocks, md_block, table_block, tool_result_guard_statuses,
)

from .. import caveats as CV
from ..blocks import finalize_blocks
from ..types import (
    RESULT_CLARIFICATION, RESULT_FAILED, RESULT_PARTIAL, RESULT_SUCCESS,
    WorkflowId, WorkflowResult,
)


def run(query: str, router: Any, doc_ids: Optional[List[str]] = None
        ) -> WorkflowResult:
    wid = WorkflowId.PROGRAMME_INVENTORY
    records = router._programme_records(doc_ids) if router else []
    if not records:
        return WorkflowResult(
            workflow_id=wid, status=RESULT_CLARIFICATION,
            answer=CV.NO_XER, caveats=[CV.NO_XER],
            blocks=[{"type": "clarification", "block_id": "clarify",
                     "question": "Please upload at least one XER programme "
                                 "file to run this analysis.", "options": []}],
        )

    from src.programme_tools import run_tool
    result = run_tool("programme.inventory", records)
    tr = result.to_dict()
    if tr.get("status") == "failed":
        return WorkflowResult(workflow_id=wid, status=RESULT_FAILED,
                              answer=tr.get("summary", "Inventory failed."))

    blocks: List[dict] = [md_block(tr.get("summary", "Programme inventory:"),
                                   "summary")]
    for i, t in enumerate(tr.get("tables") or []):
        blocks.append(table_block(t, f"table{i + 1}"))
    blocks.extend(artifact_blocks(tr))

    guards = tool_result_guard_statuses(tr)
    caveats = list(tr.get("caveats") or [])
    if len(records) == 1:
        caveats.append("Only one programme revision is available; comparison "
                       "workflows need at least two.")
    analyst = bool(tr.get("requires_analyst_review", False))
    blocks = finalize_blocks(blocks, guards, analyst, [], caveats,
                             tr.get("warnings"))
    status = RESULT_PARTIAL if analyst else RESULT_SUCCESS
    return WorkflowResult(
        workflow_id=wid, status=status, blocks=blocks,
        answer=tr.get("summary", "Programme inventory:"), caveats=caveats,
        primary_artifact=tr, analyst_review_required=analyst,
        validation={k: v for k, v in guards.items()},
    )
