"""programme.critical_path adapter — baseline planned critical path (Module 5).

Traces the driving (longest) path back from the end activity by tightest
constraint — the SCL-preferred method that does not rely on stored float —
and falls back to a float-based identification only if the trace yields
nothing. All deterministic; the LLM never touches the path.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..schemas import AdapterOutput, ArtifactBlob, ToolResult, failed_result, json_safe
from .xer_loader import load_xer_files

TOOL_ID = "programme.critical_path"


def _target_revision(inv, data_by_name):
    """The programme whose critical path to trace: the designated baseline,
    else the earliest dated revision, else the only file loaded."""
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
        baseline_file: Optional[str] = None,
        method: str = "longest_path") -> AdapterOutput:
    from ..vendor.programme import build_inventory
    from ..vendor.programme.critical_path import (
        extract_critical_path, extract_longest_path,
    )
    from ..vendor.programme.report_xlsx import build_critical_path_xlsx

    files = load_xer_files(records)
    data_by_name = dict(files)
    inv = build_inventory(files, baseline_file=baseline_file)

    label, data = _target_revision(inv, data_by_name)
    if data is None:
        return failed_result(
            TOOL_ID, "No usable programme revision was found to trace a "
                     "critical path."), []

    used_method = "longest path (driving-logic trace)"
    cp = extract_longest_path(data, label)
    if not cp.activities:
        # No incomplete-activity trace (e.g. a fully baseline-only export) —
        # fall back to float-based identification.
        cp = extract_critical_path(data, label)
        used_method = "float-based (total float ≤ tolerance)"

    if not cp.activities:
        return failed_result(
            TOOL_ID, f"No critical path could be identified in {label}; the "
                     "programme may lack logic or dated activities."), []

    def _fmt(dt):
        return dt.strftime("%Y-%m-%d") if dt else "—"

    rows = [[a.task_code, a.name, a.task_type, _fmt(a.early_start),
             _fmt(a.early_finish),
             f"{a.duration_days:.0f}" if a.duration_days is not None else "—",
             f"{a.total_float_days:+.0f}" if a.total_float_days is not None else "—",
             a.band]
            for a in cp.activities]
    tables = [{
        "title": f"Planned critical path — {label}",
        "columns": ["Activity ID", "Name", "Type", "Early start",
                    "Early finish", "Duration (d)", "Total float (d)", "Band"],
        "rows": rows,
    }]

    continuity = ("one continuous chain" if cp.is_continuous
                  else f"{cp.chain_segments} broken segment(s)")
    summary = (f"Critical path of {label} via {used_method}: "
               f"{len(cp.critical)} critical + {len(cp.near_critical)} "
               f"near-critical activit(ies), {continuity}"
               + (f", {cp.start_activity} → {cp.end_activity}"
                  if cp.start_activity and cp.end_activity else "") + ".")

    caveats = list(cp.caveats)
    if not cp.is_continuous:
        caveats.append(
            "The critical path is not a single continuous chain; broken "
            "segments usually mean constraints or missing logic, and warrant "
            "analyst review before relying on the sequence.")

    result = ToolResult(
        tool_id=TOOL_ID,
        summary=summary,
        tables=tables,
        charts=[],
        warnings=list(inv.warnings) + list(cp.warnings),
        caveats=caveats,
        requires_analyst_review=True,
        raw={"programme": label, "method": cp.method,
             "is_continuous": cp.is_continuous,
             "activities": json_safe(cp.activities)},
    )
    result._engine_ctx = {"result": cp}
    blobs = [ArtifactBlob("critical_path.xlsx", "xlsx",
                          build_critical_path_xlsx(cp))]
    return result, blobs
