"""Generic XER-programme-tool → workflow bridge.

Every programme forensic tool (variance, critical path, windows, float
erosion, …) follows the same shape: resolve the uploaded XERs, run one
whitelisted programme tool, and turn its ToolResult into blocks. This is that
shape, once. A new engine becomes a one-line dispatch, not another adapter.

The chart values come verbatim from the deterministic engine — the same
guarantee the computation guard already enforces on the tool result — so no
LLM ever authors a chart here.
"""

from __future__ import annotations

from typing import Any, List, Optional

from src.orchestration.helpers import (
    artifact_blocks, md_block, table_block, tool_result_guard_statuses,
)

from ..blocks import finalize_blocks
from ..types import RESULT_CLARIFICATION, RESULT_PARTIAL, WorkflowId, WorkflowResult


def _clarify(wid: WorkflowId, msg: str) -> WorkflowResult:
    return WorkflowResult(
        workflow_id=wid, status=RESULT_CLARIFICATION, answer=msg, caveats=[msg],
        blocks=[{"type": "clarification", "block_id": "clarify",
                 "question": msg, "options": []}])


def _chart_block(chart: dict) -> Optional[dict]:
    """Map a programme ToolResult bar chart to a ChartBlock (values copied)."""
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


def run_programme_tool_workflow(
        wid: WorkflowId, tool_id: str, router: Any,
        doc_ids: Optional[List[str]] = None, *,
        min_files: int = 2, need_message: str = "") -> WorkflowResult:
    """Resolve XERs, run one programme tool, render its result as blocks."""
    records = router._programme_records(doc_ids) if router else []
    if len(records) < min_files:
        return _clarify(wid, need_message or (
            f"This analysis needs at least {min_files} programme XER file(s)."))

    from src.programme_tools import run_tool
    tr = run_tool(tool_id, records).to_dict()
    if tr.get("status") == "failed":
        # An unavailable analysis (missing codes, too few revisions, no logic)
        # is an informative answer, not a crash.
        return _clarify(wid, tr.get("summary", "This analysis is unavailable."))

    blocks: List[dict] = [md_block(tr.get("summary", ""), "summary")]
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
        answer=tr.get("summary", ""), caveats=caveats, primary_artifact=tr,
        analyst_review_required=analyst,
        validation={k: v for k, v in guards.items()})
