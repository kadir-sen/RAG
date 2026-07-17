"""programme.asbuilt_path adapter — As-Built Critical Path (Module 12).

Reconstructs the as-built critical path contemporaneously: window-by-window
driving paths stitched together, with a criticality-persistence index (how
often an activity sat on the driving path while it was eligible). This is the
basis of a collapsed/observational as-built analysis. All deterministic; the
LLM never touches the path.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..schemas import AdapterOutput, ToolResult, failed_result, json_safe
from .xer_loader import load_xer_files

TOOL_ID = "programme.asbuilt_path"

_TOP = 60


def run(records: List[Dict[str, Any]],
        baseline_file: Optional[str] = None) -> AdapterOutput:
    from ..vendor.programme import build_inventory
    from ..vendor.programme.asbuilt_path import analyse_asbuilt_path

    files = load_xer_files(records)
    data_by_name = dict(files)
    inv = build_inventory(files, baseline_file=baseline_file)

    dated = [r for r in inv.revisions if r.data_date is not None]
    if len(dated) < 2:
        return failed_result(
            TOOL_ID, "An as-built critical path is reconstructed across "
                     "successive programmes; it needs at least two dated "
                     "revisions (three or more give a stronger trace)."), []
    dated.sort(key=lambda r: r.data_date)
    revisions = [(r.label, data_by_name[r.file_name]) for r in dated]

    ab = analyse_asbuilt_path(revisions)
    if not ab.persistence:
        return failed_result(
            TOOL_ID, "No activity persisted on the driving path across these "
                     "revisions, so an as-built critical path could not be "
                     "reconstructed."), []

    def _fmt(dt):
        return dt.strftime("%Y-%m-%d") if dt else "—"

    ranked = sorted(
        ab.persistence,
        key=lambda p: (-(p.times_on_path / p.times_eligible
                         if p.times_eligible else 0), -p.times_on_path))[:_TOP]
    rows = [[p.task_code, p.name, f"{p.times_on_path}/{p.times_eligible}",
             f"{(p.times_on_path / p.times_eligible):.0%}"
             if p.times_eligible else "—",
             _fmt(p.act_start), _fmt(p.act_finish),
             "yes" if p.is_complete else "no"]
            for p in ranked]
    tables = [{
        "title": "As-built critical path — criticality persistence",
        "columns": ["Activity", "Name", "On path / eligible", "Persistence",
                    "Actual start", "Actual finish", "Complete"],
        "rows": rows,
    }]

    summary = (f"Across {ab.revision_count} revision(s), {len(ab.core_codes)} "
               f"activity(ies) formed the core as-built critical path "
               f"(persisting on the driving path in most windows); "
               f"{len(ab.persistence)} activit(ies) touched it at least once.")

    result = ToolResult(
        tool_id=TOOL_ID,
        summary=summary,
        tables=tables,
        charts=[],
        warnings=list(inv.warnings) + list(ab.warnings),
        caveats=list(ab.caveats),
        requires_analyst_review=True,
        raw={"revision_count": ab.revision_count,
             "core_codes": list(ab.core_codes),
             "persistence": json_safe(ab.persistence)},
    )
    result._engine_ctx = {"result": ab}
    return result, []
