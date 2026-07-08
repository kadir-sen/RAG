"""programme.milestone_shift adapter — milestone drift across XER revisions.

Fuzzy name matches are NEVER auto-merged: the engine returns them as
needs_confirmation proposals and this adapter surfaces them verbatim with an
analyst-confirmation flag.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..schemas import AdapterOutput, ArtifactBlob, ToolResult, json_safe
from .xer_loader import load_xer_files

TOOL_ID = "programme.milestone_shift"

_CHART_TOP_N = 8


def run(records: List[Dict[str, Any]],
        baseline_file: Optional[str] = None) -> AdapterOutput:
    from ..vendor.programme import build_inventory, track_milestone_shifts
    from ..vendor.programme.report_xlsx import build_milestone_xlsx

    files = load_xer_files(records)
    inv = build_inventory(files, baseline_file=baseline_file)
    data_by_name = dict(files)
    # Same construction as the upstream app: only revisions with a data date
    # participate, in the inventory's data-date order.
    revs = [(r.label, r.data_date, data_by_name[r.file_name])
            for r in inv.revisions if r.data_date is not None]
    dropped = len(inv.revisions) - len(revs)

    shifts = track_milestone_shifts(revs)

    # Upstream app's selection rule: series appearing in >1 revision with a
    # computable shift, ranked by absolute shift.
    plottable = [s for s in shifts.series
                 if len(s.dated_points) > 1 and s.total_shift_days is not None]
    plottable.sort(key=lambda s: -abs(s.total_shift_days))
    top = plottable[:_CHART_TOP_N]

    def _d(dt):
        return dt.strftime("%Y-%m-%d") if dt else "—"

    summary_rows = [
        [s.key, s.name,
         f"{s.total_shift_days:+.0f}" if s.total_shift_days is not None else "—",
         "yes" if s.is_achieved else "no",
         _d(s.first_value), _d(s.last_value)]
        for s in sorted(shifts.series,
                        key=lambda s: -(abs(s.total_shift_days or 0)))
    ]
    tables = [{
        "title": "Milestone shift summary",
        "columns": ["Milestone", "Name", "Total shift (days)", "Achieved",
                    "First date", "Latest date"],
        "rows": summary_rows,
    }]

    if shifts.needs_confirmation:
        tables.append({
            "title": "Possible milestone matches — analyst confirmation "
                     "required; NOT merged into results",
            "columns": ["Revision", "Activity ID", "Activity name",
                        "Possible match (key)", "Possible match (name)",
                        "Similarity"],
            "rows": [[m.revision_label, m.task_code, m.task_name,
                      m.matched_to_key, m.matched_to_name,
                      f"{m.similarity:.0%}"]
                     for m in shifts.needs_confirmation],
        })

    charts = []
    if top:
        charts.append({
            "chart_id": "milestone_shift",
            "type": "line",
            "title": "Milestone forecast/actual dates by revision data date",
            "x_label": "Revision data date",
            "y_label": "Milestone date",
            "series": [{
                "name": f"{s.key} — {s.name}",
                "points": [{
                    "x": p.data_date.isoformat(),
                    "y": p.value_date.isoformat() if p.value_date else None,
                    "marker": "achieved" if p.is_actual else None,
                } for p in s.points],
            } for s in top],
        })

    warnings = list(inv.warnings) + list(shifts.warnings)
    caveats = list(inv.missing)
    if dropped:
        caveats.append(
            f"{dropped} revision(s) without a data date were excluded from "
            "milestone tracking."
        )
    if shifts.needs_confirmation:
        caveats.append(
            f"{len(shifts.needs_confirmation)} candidate milestone match(es) "
            "were NOT auto-merged; analyst confirmation is required."
        )
    caveats.append(
        "Milestone dates reflect forecast/actual values as recorded in each "
        "P6 revision; recorded dates are not independently verified facts."
    )

    slipped = [s for s in shifts.series
               if s.total_shift_days and s.total_shift_days > 0]
    summary = (f"Tracked {len(shifts.series)} milestone(s) across "
               f"{len(revs)} revision(s); {len(slipped)} slipped later than "
               "first forecast.")

    result = ToolResult(
        tool_id=TOOL_ID,
        summary=summary,
        tables=tables,
        charts=charts,
        warnings=warnings,
        caveats=caveats,
        requires_analyst_review=bool(shifts.needs_confirmation) or dropped > 0,
        raw={"series": json_safe(shifts.series),
             "needs_confirmation": json_safe(shifts.needs_confirmation),
             "revisions_used": [label for label, _, _ in revs]},
    )
    # Engine objects for the narrative prompt builders (not serialized).
    result._engine_ctx = {"result": shifts, "series": top}
    blobs = [ArtifactBlob("milestone_shift.xlsx", "xlsx",
                          build_milestone_xlsx(shifts, top))]
    return result, blobs
