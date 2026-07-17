"""programme.progress adapter — Progress S-curve (Module 8).

Planned cumulative progress (from the baseline) vs as-recorded progress (from
the latest update), with the slippage read as the horizontal offset between the
two curves. Weighting is by activity duration (equal / resource optional). All
deterministic; the LLM never touches the curve.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..schemas import AdapterOutput, ToolResult, failed_result, json_safe
from .xer_loader import load_xer_files

TOOL_ID = "programme.progress"


def run(records: List[Dict[str, Any]],
        baseline_file: Optional[str] = None,
        weight_scheme: str = "duration") -> AdapterOutput:
    from ..vendor.programme import build_inventory
    from ..vendor.programme.progress import compute_progress

    files = load_xer_files(records)
    data_by_name = dict(files)
    inv = build_inventory(files, baseline_file=baseline_file)

    dated = [r for r in inv.revisions if r.data_date is not None]
    if len(dated) < 2:
        return failed_result(
            TOOL_ID, "A progress curve needs a baseline and at least one "
                     "later update (two dated revisions)."), []
    dated.sort(key=lambda r: r.data_date)
    base_rev = inv.baseline or dated[0]
    base_data = data_by_name[base_rev.file_name]
    updates = [(r.label, data_by_name[r.file_name]) for r in dated
               if r.file_name != base_rev.file_name]

    pr = compute_progress(base_data, base_rev.label, updates,
                          weight_scheme=weight_scheme)

    def _series(curve, name):
        return {"name": name,
                "points": [{"x": p.date.isoformat(), "y": round(p.cum_pct, 2)}
                           for p in curve]}

    charts = []
    if pr.planned_curve or pr.recorded_curve:
        charts.append({
            "chart_id": "progress_scurve",
            "type": "line",
            "title": "Planned vs as-recorded cumulative progress",
            "x_label": "Date",
            "y_label": "Cumulative % complete",
            "series": [_series(pr.planned_curve, "Planned"),
                       _series(pr.recorded_curve, "As-recorded")],
        })

    offset = pr.time_offset_days
    offset_txt = ("on plan" if offset is None else
                  f"{abs(offset):.0f} days {'behind' if offset > 0 else 'ahead of'} plan")
    rows = [
        ["Planned % at data date",
         f"{pr.planned_pct_at_dd:.1f}%" if pr.planned_pct_at_dd is not None else "—"],
        ["Recorded % at data date",
         f"{pr.recorded_pct_at_dd:.1f}%" if pr.recorded_pct_at_dd is not None else "—"],
        ["Time offset (days)",
         f"{offset:+.0f}" if offset is not None else "—"],
        ["Weighting", weight_scheme],
    ]
    tables = [{"title": "Progress summary", "columns": ["Metric", "Value"],
               "rows": rows}]

    summary = (f"As-recorded progress is {offset_txt} as at the latest data "
               f"date (planned {pr.planned_pct_at_dd:.0f}% vs recorded "
               f"{pr.recorded_pct_at_dd:.0f}%)."
               if pr.planned_pct_at_dd is not None
               and pr.recorded_pct_at_dd is not None
               else "Progress curve computed.")

    result = ToolResult(
        tool_id=TOOL_ID,
        summary=summary,
        tables=tables,
        charts=charts,
        warnings=list(inv.warnings) + list(pr.warnings),
        caveats=list(pr.caveats),
        requires_analyst_review=True,
        raw={"baseline": base_rev.label, "recorded": pr.recorded_label,
             "time_offset_days": offset,
             "planned_curve": json_safe(pr.planned_curve),
             "recorded_curve": json_safe(pr.recorded_curve)},
    )
    result._engine_ctx = {"result": pr}
    return result, []
