"""programme.variance adapter — As-Planned vs As-Recorded (Module 4).

Compares a baseline programme against the latest recorded one, grouped by a
P6 activity-code dimension, and reports each group's start/finish slippage.

The dimension is chosen deterministically (the most-assigned activity-code
type), never by the LLM. If the export carries no activity codes the tool
reports that variance is unavailable rather than inventing a grouping.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..schemas import AdapterOutput, ArtifactBlob, ToolResult, failed_result, json_safe
from .xer_loader import load_xer_files

TOOL_ID = "programme.variance"

_CHART_TOP_N = 12


def _pick_baseline_recorded(inv, data_by_name):
    """(baseline_rev, recorded_rev) as (label, XerData) pairs, or (None, None).

    Baseline is the designated one if the inventory flags it, else the earliest
    data date; recorded is the latest. Both must have a data date and differ.
    """
    dated = [r for r in inv.revisions if r.data_date is not None]
    if len(dated) < 2:
        return None, None
    dated.sort(key=lambda r: r.data_date)
    base_rev = inv.baseline or dated[0]
    rec_rev = dated[-1]
    if base_rev.file_name == rec_rev.file_name:
        # Designated baseline is also the latest — fall back to earliest.
        base_rev = dated[0]
        if base_rev.file_name == rec_rev.file_name:
            return None, None
    return ((base_rev.label, data_by_name[base_rev.file_name]),
            (rec_rev.label, data_by_name[rec_rev.file_name]))


def run(records: List[Dict[str, Any]],
        baseline_file: Optional[str] = None,
        code_type_id: Optional[str] = None) -> AdapterOutput:
    from ..vendor.programme import build_inventory
    from ..vendor.programme.activity_codes import (
        activity_code_types, task_code_assignments,
    )
    from ..vendor.programme.report_xlsx import build_variance_xlsx
    from ..vendor.programme.variance import compute_variance_by_mapping

    files = load_xer_files(records)
    data_by_name = dict(files)
    inv = build_inventory(files, baseline_file=baseline_file)

    (base, recorded) = _pick_baseline_recorded(inv, data_by_name)
    if base is None:
        return failed_result(
            TOOL_ID,
            "Variance needs two dated programme revisions (a baseline and a "
            "later recorded programme); fewer than two were available."), []
    base_label, base_data = base
    rec_label, rec_data = recorded

    # Deterministic dimension choice: the richest activity-code type, or a
    # caller-pinned one. No activity codes → variance is genuinely unavailable.
    types = activity_code_types(base_data)
    if not types:
        return failed_result(
            TOOL_ID,
            "The baseline export carries no activity codes, so an "
            "as-planned vs as-recorded breakdown cannot be grouped. Re-export "
            "the programme with activity codes, or use a WBS-based comparison."), []
    chosen = next((t for t in types if t.type_id == code_type_id), types[0])

    base_map = task_code_assignments(base_data, chosen.type_id)
    rec_map = task_code_assignments(rec_data, chosen.type_id)
    var = compute_variance_by_mapping(base_data, rec_data, base_map, rec_map,
                                      chosen.name)

    def _fmt(dt):
        return dt.strftime("%Y-%m-%d") if dt else "—"

    def _delta(v):
        return f"{v:+.0f}" if v is not None else "—"

    rows = [[g.code_value, _fmt(g.planned.start), _fmt(g.planned.finish),
             _fmt(g.recorded.start), _fmt(g.recorded.finish),
             _delta(g.start_delta_days), _delta(g.finish_delta_days),
             g.planned.activity_count, g.recorded.activity_count]
            for g in var.groups]
    tables = [{
        "title": f"As-planned vs as-recorded — by {chosen.name}",
        "columns": [chosen.name, "Planned start", "Planned finish",
                    "Recorded start", "Recorded finish", "Δ start (days)",
                    "Δ finish (days)", "Planned acts", "Recorded acts"],
        "rows": rows,
    }]

    # Bar chart of the worst finish slips (deterministic; values copied from
    # the engine, never recomputed by an LLM).
    worst = [g for g in var.worst_finish_slips
             if g.finish_delta_days is not None][:_CHART_TOP_N]
    charts = []
    if worst:
        charts.append({
            "chart_id": "variance_finish_slip",
            "type": "bar",
            "title": f"Finish slippage by {chosen.name} (as-recorded vs planned)",
            "x_label": chosen.name,
            "y_label": "Finish slip (days)",
            "categories": [g.code_value for g in worst],
            "values": [round(g.finish_delta_days, 1) for g in worst],
        })

    slipped = [g for g in var.groups
               if g.finish_delta_days and g.finish_delta_days > 0]
    summary = (f"Compared {base_label} against {rec_label} across "
               f"{len(var.groups)} {chosen.name} group(s); {len(slipped)} "
               "finished later than planned.")

    caveats = list(var.caveats)
    caveats.append(
        f"Grouped by the most-populated activity-code type ('{chosen.name}'); "
        "another dimension may tell a different story.")
    caveats.append(
        "Recorded dates are as stated in the P6 export, not independently "
        "verified; variance describes schedule movement, not its cause.")

    result = ToolResult(
        tool_id=TOOL_ID,
        summary=summary,
        tables=tables,
        charts=charts,
        warnings=list(inv.warnings) + list(var.warnings),
        caveats=caveats,
        requires_analyst_review=True,
        raw={"dimension": chosen.name,
             "baseline": base_label, "recorded": rec_label,
             "groups": json_safe(var.groups)},
    )
    result._engine_ctx = {"result": var}
    blobs = [ArtifactBlob("variance.xlsx", "xlsx", build_variance_xlsx(var))]
    return result, blobs
