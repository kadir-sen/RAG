"""preliminary_programme_pack workflow — wraps run_pack (no composite)."""

from __future__ import annotations

from typing import Any, List, Optional

from src.orchestration.helpers import md_block

from .. import caveats as CV
from ..blocks import finalize_blocks
from ..types import (
    RESULT_CLARIFICATION, RESULT_PARTIAL, RESULT_SUCCESS,
    WorkflowId, WorkflowResult,
)


def run(query: str, router: Any, doc_ids: Optional[List[str]] = None
        ) -> WorkflowResult:
    wid = WorkflowId.PRELIMINARY_PROGRAMME_PACK
    records = router._programme_records(doc_ids) if router else []
    if not records:
        return WorkflowResult(
            workflow_id=wid, status=RESULT_CLARIFICATION,
            answer=CV.NO_XER, caveats=[CV.NO_XER],
            blocks=[{"type": "clarification", "block_id": "clarify",
                     "question": "Please upload at least one XER programme "
                                 "file to build the pack.", "options": []}],
        )

    from src.programme_tools.workflows.preliminary_programme_analysis import (
        run_pack,
    )
    pack = run_pack(records)

    blocks: List[dict] = []
    for i, s in enumerate(pack.get("sections") or []):
        blocks.append(md_block(f"## {s.get('title', '')}\n\n"
                               f"{s.get('narrative', '')}", f"section{i + 1}"))

    caveats: List[str] = [CV.DCMA_HEALTH_NOT_DELAY, CV.MOVEMENT_NOT_CAUSATION]
    if len(records) < 2:
        caveats.append(CV.ONE_XER_ONLY)
    fallbacks: List[str] = []
    partial = pack.get("status") != "complete"
    if partial:
        fallbacks.append("pack partial")
    guards = {"pack_guard": "fallback" if partial else "passed"}
    blocks = finalize_blocks(blocks, guards, False, fallbacks, caveats)
    status = RESULT_PARTIAL if partial else RESULT_SUCCESS
    return WorkflowResult(
        workflow_id=wid, status=status, blocks=blocks,
        answer="Preliminary programme analysis pack:", caveats=caveats,
        primary_artifact=pack, validation=guards,
    )
