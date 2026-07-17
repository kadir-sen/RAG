"""programme.float_erosion adapter — Float Erosion Tracker (Module 9).

Tracks how total float is consumed across revisions: per window, how many
activities lost float (eroded) or gained it, and the median change — the
early-warning signal that shows pressure building before visible slippage. All
deterministic; the LLM never touches the numbers.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..schemas import AdapterOutput, ToolResult, failed_result, json_safe
from .xer_loader import load_xer_files

TOOL_ID = "programme.float_erosion"


def run(records: List[Dict[str, Any]],
        baseline_file: Optional[str] = None) -> AdapterOutput:
    from ..vendor.programme import build_inventory
    from ..vendor.programme.float_erosion import analyse_float_erosion

    files = load_xer_files(records)
    data_by_name = dict(files)
    inv = build_inventory(files, baseline_file=baseline_file)

    dated = [r for r in inv.revisions if r.data_date is not None]
    if len(dated) < 2:
        return failed_result(
            TOOL_ID, "Float erosion tracking needs at least two dated "
                     "programme revisions."), []
    dated.sort(key=lambda r: r.data_date)
    revisions = [(r.label, data_by_name[r.file_name]) for r in dated]

    fe = analyse_float_erosion(revisions)
    if not fe.windows:
        return failed_result(
            TOOL_ID, "No usable windows could be formed to track float "
                     "erosion."), []

    rows = [[f"W{w.index}", f"{w.from_label} → {w.to_label}", w.matched,
             f"{w.median_delta:+.1f}" if w.median_delta is not None else "—",
             w.eroded_count, w.gained_count]
            for w in fe.windows]
    tables = [{
        "title": "Float erosion by window",
        "columns": ["Window", "Span", "Activities matched",
                    "Median Δ float (days)", "Eroded", "Gained"],
        "rows": rows,
    }]

    charts = [{
        "chart_id": "float_erosion",
        "type": "bar",
        "title": "Activities losing float per window",
        "x_label": "Window",
        "y_label": "Eroded activities",
        "categories": [f"W{w.index}" for w in fe.windows],
        "values": [w.eroded_count for w in fe.windows],
    }]

    total_eroded = sum(w.eroded_count for w in fe.windows)
    summary = (f"Across {len(fe.windows)} window(s), {total_eroded} activity-"
               "instance(s) lost float — float erosion precedes visible "
               "slippage, so this is an early-warning view.")

    result = ToolResult(
        tool_id=TOOL_ID,
        summary=summary,
        tables=tables,
        charts=charts,
        warnings=list(inv.warnings) + list(fe.warnings),
        caveats=list(fe.caveats),
        requires_analyst_review=True,
        raw={"near_days": fe.near_days,
             "snapshots": json_safe(fe.snapshots),
             "windows": json_safe(fe.windows)},
    )
    result._engine_ctx = {"result": fe}
    return result, []
