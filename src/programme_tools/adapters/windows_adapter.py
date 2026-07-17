"""programme.windows adapter — Windows / Period Movement analysis (Module 7).

For each consecutive data-date window: how far the completion date moved, and
which activities entered or left the driving (longest) path — the
contemporaneous, window-by-window method the SCL Protocol prefers. All
deterministic; the LLM never touches the analysis.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..schemas import AdapterOutput, ToolResult, failed_result, json_safe
from .xer_loader import load_xer_files

TOOL_ID = "programme.windows"


def run(records: List[Dict[str, Any]],
        baseline_file: Optional[str] = None) -> AdapterOutput:
    from ..vendor.programme import build_inventory
    from ..vendor.programme.windows import analyse_windows

    files = load_xer_files(records)
    data_by_name = dict(files)
    inv = build_inventory(files, baseline_file=baseline_file)

    dated = [r for r in inv.revisions if r.data_date is not None]
    if len(dated) < 2:
        return failed_result(
            TOOL_ID, "Windows analysis needs at least two dated programme "
                     "revisions to form a window."), []
    dated.sort(key=lambda r: r.data_date)
    revisions = [(r.label, data_by_name[r.file_name]) for r in dated]

    wr = analyse_windows(revisions)
    if not wr.windows:
        return failed_result(
            TOOL_ID, "No usable windows could be formed from these "
                     "revisions."), []

    def _fmt(dt):
        return dt.strftime("%Y-%m-%d") if dt else "—"

    rows = [[f"W{w.index}", f"{w.from_label} → {w.to_label}",
             f"{w.window_days:.0f}" if w.window_days is not None else "—",
             _fmt(w.finish_old), _fmt(w.finish_new),
             f"{w.movement_days:+.0f}" if w.movement_days is not None else "—",
             f"{w.cp_retained}/{w.cp_new_count}",
             f"{w.cp_similarity:.0%}" if w.cp_similarity is not None else "—"]
            for w in wr.windows]
    tables = [{
        "title": "Period movement by window",
        "columns": ["Window", "Span", "Days", "Finish was", "Finish now",
                    "Movement (days)", "CP retained", "CP similarity"],
        "rows": rows,
    }]

    charts = []
    movers = [w for w in wr.windows if w.movement_days is not None]
    if movers:
        charts.append({
            "chart_id": "window_movement",
            "type": "bar",
            "title": "Completion-date movement by window",
            "x_label": "Window",
            "y_label": "Movement (days)",
            "categories": [f"W{w.index}" for w in movers],
            "values": [round(w.movement_days, 1) for w in movers],
        })

    total = wr.total_movement_days
    summary = (f"Across {len(wr.windows)} window(s), the completion date moved "
               + (f"{total:+.0f} days net" if total is not None else "by an "
                  "indeterminate amount")
               + "; each window also reports how much of the critical path was "
               "retained.")

    result = ToolResult(
        tool_id=TOOL_ID,
        summary=summary,
        tables=tables,
        charts=charts,
        warnings=list(inv.warnings) + list(wr.warnings),
        caveats=list(wr.caveats),
        requires_analyst_review=True,
        raw={"total_movement_days": total,
             "windows": json_safe(wr.windows)},
    )
    result._engine_ctx = {"result": wr}
    return result, []
