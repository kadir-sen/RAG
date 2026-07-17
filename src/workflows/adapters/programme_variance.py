"""programme_variance workflow — wraps programme.variance (no composite).

As-planned vs as-recorded slippage by activity-code dimension. The chart's
values come verbatim from the deterministic engine (never an LLM), the same
guarantee the computation guard already enforces on the tool result.
"""

from __future__ import annotations

from typing import Any, List, Optional

from src.orchestration.helpers import (
    artifact_blocks, md_block, table_block, tool_result_guard_statuses,
)

from ..blocks import finalize_blocks
from ..types import (
    RESULT_CLARIFICATION, RESULT_FAILED, RESULT_PARTIAL, WorkflowId,
    WorkflowResult,
)


def _chart_block(chart: dict) -> Optional[dict]:
    """Map a programme ToolResult chart (bar) to a ChartBlock. Values are the
    engine's, copied through — this is not an LLM-authored chart."""
    if chart.get("type") != "bar":
        return None
    cats = chart.get("categories") or []
    vals = chart.get("values") or []
    if not cats or len(cats) != len(vals):
        return None
    return {"type": "chart", "block_id": chart.get("chart_id", "chart"),
            "chart_type": "bar", "title": chart.get("title", ""),
            "x_label": chart.get("x_label", ""),
            "y_label": chart.get("y_label", ""),
            "categories": [str(c) for c in cats],
            "values": [float(v) for v in vals]}


def run(query: str, router: Any, doc_ids: Optional[List[str]] = None
        ) -> WorkflowResult:
    wid = WorkflowId.PROGRAMME_VARIANCE
    records = router._programme_records(doc_ids) if router else []
    if len(records) < 2:
        msg = ("As-planned vs as-recorded variance needs a baseline and at "
               "least one later programme revision. Upload two dated .xer "
               "files.")
        return WorkflowResult(
            workflow_id=wid, status=RESULT_CLARIFICATION, answer=msg,
            caveats=[msg],
            blocks=[{"type": "clarification", "block_id": "clarify",
                     "question": msg, "options": []}])

    from src.programme_tools import run_tool
    tr = run_tool("programme.variance", records).to_dict()
    if tr.get("status") == "failed":
        # A missing-activity-codes / one-revision failure is an informative
        # answer, not a crash — surface it as a clarification.
        msg = tr.get("summary", "Variance analysis is unavailable.")
        return WorkflowResult(
            workflow_id=wid, status=RESULT_CLARIFICATION, answer=msg,
            caveats=[msg],
            blocks=[{"type": "clarification", "block_id": "clarify",
                     "question": msg, "options": []}])

    blocks: List[dict] = [md_block(tr.get("summary", "Variance:"), "summary")]
    for i, t in enumerate(tr.get("tables") or []):
        blocks.append(table_block(t, f"table{i + 1}"))
    for c in tr.get("charts") or []:
        cb = _chart_block(c)
        if cb:
            blocks.append(cb)
    blocks.extend(artifact_blocks(tr))

    guards = tool_result_guard_statuses(tr)
    caveats = list(tr.get("caveats") or [])
    analyst = bool(tr.get("requires_analyst_review", True))
    blocks = finalize_blocks(blocks, guards, analyst, [], caveats,
                             tr.get("warnings"))
    return WorkflowResult(
        workflow_id=wid, status=RESULT_PARTIAL, blocks=blocks,
        answer=tr.get("summary", "Variance:"), caveats=caveats,
        primary_artifact=tr, analyst_review_required=analyst,
        validation={k: v for k, v in guards.items()})
