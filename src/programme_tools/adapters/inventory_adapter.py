"""programme.inventory adapter — catalogue XER revisions (baseline/current)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..schemas import AdapterOutput, ArtifactBlob, ToolResult, json_safe
from .xer_loader import load_xer_files

TOOL_ID = "programme.inventory"


def run(records: List[Dict[str, Any]],
        baseline_file: Optional[str] = None) -> AdapterOutput:
    """Build the programme inventory. Baseline/current designation and
    data-date ordering come from the ENGINE (build_inventory), never recomputed
    here."""
    from ..vendor.programme import build_inventory
    from ..vendor.programme.report_xlsx import build_inventory_xlsx

    files = load_xer_files(records)
    # v1: document-availability flags are not assessed from the corpus yet.
    inv = build_inventory(files, baseline_file=baseline_file)

    def _d(dt):  # short ISO date or em-dash
        return dt.strftime("%Y-%m-%d") if dt else "—"

    rows = [
        [r.label, r.file_name, r.project_short_name or "—", _d(r.data_date),
         _d(r.plan_start), _d(r.scheduled_finish), r.activity_count,
         r.relationship_count, r.milestone_count,
         "baseline" if r.is_baseline else ("current" if r.is_current else "")]
        for r in inv.revisions
    ]
    tables = [{
        "title": "Programme revisions",
        "columns": ["Revision", "File", "Project", "Data date", "Plan start",
                    "Scheduled finish", "Activities", "Relationships",
                    "Milestones", "Role"],
        "rows": rows,
    }]

    caveats = list(inv.missing)
    caveats.append(
        "Availability of correspondence, contract and labour records was not "
        "assessed in this run."
    )

    baseline_label = inv.baseline.label if inv.baseline else "not identified"
    current_label = inv.current.label if inv.current else "not identified"
    summary = (f"{len(inv.revisions)} programme revision(s) inventoried; "
               f"baseline={baseline_label}, current={current_label}.")

    result = ToolResult(
        tool_id=TOOL_ID,
        summary=summary,
        tables=tables,
        warnings=list(inv.warnings),
        caveats=caveats,
        raw={"inventory": json_safe(inv)},
    )
    # Engine objects for the narrative prompt builders (not serialized).
    result._engine_ctx = {"inventory": inv}
    blobs = [ArtifactBlob("programme_inventory.xlsx", "xlsx",
                          build_inventory_xlsx(inv))]
    return result, blobs
