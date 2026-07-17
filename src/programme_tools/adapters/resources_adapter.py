"""programme.resources adapter — Planned Resource Histograms (Module 10).

Monthly planned resource loading (labour / equipment / material) from the
programme's TASKRSRC target quantities. Needs a resourced programme; if none
is loaded it says so rather than inventing a histogram. All deterministic;
the LLM never touches the loading.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from ..schemas import AdapterOutput, ToolResult, failed_result, json_safe
from .xer_loader import load_xer_files

TOOL_ID = "programme.resources"

_TOP_RESOURCES = 20


def _target_revision(inv, data_by_name):
    if inv.baseline is not None:
        r = inv.baseline
        return r.label, data_by_name[r.file_name]
    dated = [r for r in inv.revisions if r.data_date is not None]
    if dated:
        dated.sort(key=lambda r: r.data_date)
        return dated[0].label, data_by_name[dated[0].file_name]
    if inv.revisions:
        r = inv.revisions[0]
        return r.label, data_by_name[r.file_name]
    return None, None


def run(records: List[Dict[str, Any]],
        baseline_file: Optional[str] = None) -> AdapterOutput:
    from ..vendor.programme import build_inventory
    from ..vendor.programme.resources import extract_resource_loading

    files = load_xer_files(records)
    data_by_name = dict(files)
    inv = build_inventory(files, baseline_file=baseline_file)

    label, data = _target_revision(inv, data_by_name)
    if data is None:
        return failed_result(
            TOOL_ID, "No usable programme revision was found for resource "
                     "loading."), []

    rl = extract_resource_loading(data, label)
    if not rl.histogram:
        return failed_result(
            TOOL_ID, "This programme carries no resource assignments "
                     "(TASKRSRC), so no planned loading histogram can be "
                     "built. Re-export the programme with resources loaded."), []

    # Resource summary, heaviest first.
    top = sorted(rl.resources, key=lambda r: -r.total_qty)[:_TOP_RESOURCES]
    tables = [{
        "title": f"Planned resource loading — {label}",
        "columns": ["Resource", "Name", "Type", "Total qty", "Assignments"],
        "rows": [[r.short_name, r.name, r.rsrc_type, round(r.total_qty, 1),
                  r.assignment_count] for r in top],
    }]

    # Monthly total loading across all resources — a line chart.
    by_month: Dict[Any, float] = defaultdict(float)
    for p in rl.histogram:
        by_month[p.month_end] += p.qty
    months = sorted(by_month)
    charts = [{
        "chart_id": "resource_loading",
        "type": "line",
        "title": "Planned monthly resource loading (all resources)",
        "x_label": "Month",
        "y_label": "Planned quantity",
        "series": [{"name": "Planned loading",
                    "points": [{"x": m.isoformat(), "y": round(by_month[m], 1)}
                               for m in months]}],
    }]

    caveats = list(rl.caveats)
    if rl.unassigned_activities:
        caveats.append(
            f"{rl.unassigned_activities} activit(ies) carry no resource "
            "assignment; the histogram under-represents those periods.")

    summary = (f"Planned loading for {len(rl.resources)} resource(s) across "
               f"{len(months)} month(s); heaviest: "
               f"{top[0].short_name} ({top[0].total_qty:,.0f}).")

    result = ToolResult(
        tool_id=TOOL_ID,
        summary=summary,
        tables=tables,
        charts=charts,
        warnings=list(inv.warnings) + list(rl.warnings),
        caveats=caveats,
        requires_analyst_review=True,
        raw={"programme": label,
             "resources": json_safe(rl.resources),
             "unassigned_activities": rl.unassigned_activities},
    )
    result._engine_ctx = {"result": rl}
    return result, []
