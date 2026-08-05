"""Explicit React view models for every pinned upstream analysis screen.

No recursive table discovery or guessed chart exists here.  Each path is a
reviewed part of the bb52fa0 output contract, so a changed upstream result
fails visibly instead of silently producing a plausible generic table.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple


ViewSpec = Dict[str, Any]


MODULE_VIEW_SPECS: Dict[str, ViewSpec] = {
    "intake": {"metrics": [("Programme revisions", "revisions", "len")],
               "tables": [("Programme inventory", "revisions")]},
    "dcma": {"metrics": [("Checks", "checks", "len"),
                           ("Driving trace ties", "trace.chain.tie_count", None)],
             "tables": [("DCMA checks", "checks"), ("Driving trace", "trace.chain.steps"),
                        ("Check offenders", "trace.offenders")],
             "warnings": ["trace.warnings"], "caveats": ["trace.caveats"]},
    "baseline-critical-path": {
        "metrics": [("Method", "method", None), ("Activities", "activities", "len"),
                    ("Continuous chain", "is_continuous", None),
                    ("Chain segments", "chain_segments", None),
                    ("Start activity", "start_activity", None),
                    ("End activity", "end_activity", None),
                    ("Near-critical threshold (days)", "near_critical_days", None)],
        "tables": [("Critical and near-critical activities", "activities")],
    },
    "revision-comparison": {
        "metrics": [("Old completion", "comparison.old_finish", None),
                    ("New completion", "comparison.new_finish", None),
                    ("Completion movement (days)", "impact.completion_moved_days", None),
                    ("Kernel movement (days)", "attribution.kernel_moved_days", None)],
        "tables": [("Added activities", "comparison.added"),
                   ("Deleted activities", "comparison.deleted"),
                   ("Renamed activities", "comparison.renamed"),
                   ("Duration changes", "comparison.duration_changes"),
                   ("Logic added", "comparison.logic_added"),
                   ("Logic removed", "comparison.logic_removed"),
                   ("Lag changes", "comparison.lag_changes"),
                   ("Constraint changes", "comparison.constraint_changes"),
                   ("Impact ranking", "impact.ranked"),
                   ("Attribution changes", "attribution.changes"),
                   ("Driving chain", "attribution.driving_chain")],
        "warnings": ["comparison.warnings", "impact.warnings", "attribution.warnings"],
        "caveats": ["comparison.caveats", "impact.caveats", "attribution.caveats"],
    },
    "out-of-sequence": {
        "metrics": [("Current flags", "flags", "len"), ("Repair rows", "repair_plan", "len"),
                    ("Repair QA passed", "repair_report.qa_passed", None),
                    ("Applied repairs", "repair_report.applied", "len")],
        "tables": [("Out-of-sequence flags", "flags"), ("Editable repair plan", "repair_plan"),
                   ("Applied repairs", "repair_report.applied"),
                   ("Per revision", "evolution.per_revision"),
                   ("Evolution windows", "evolution.windows")],
        "warnings": ["evolution.warnings"], "caveats": ["evolution.caveats"],
        "chart": ("evolution.windows", "to_label", "total_after", "line"),
    },
    "float-erosion": {
        "metrics": [("Near-critical threshold (days)", "near_days", None),
                    ("Revisions", "snapshots", "len")],
        "tables": [("Float snapshots", "snapshots"), ("Window movements", "windows")],
        "chart": ("snapshots", "data_date", "median_float", "line"),
    },
    "progress-s-curve": {
        "metrics": [("Weighting", "weight_scheme", None),
                    ("Planned at data date (%)", "planned_pct_at_dd", None),
                    ("Recorded at data date (%)", "recorded_pct_at_dd", None),
                    ("Time offset (days)", "time_offset_days", None)],
        "tables": [("Planned curve", "planned_curve"), ("Recorded curve", "recorded_curve"),
                   ("Revision points", "revision_points")],
        "chart": ("revision_points", "data_date", "recorded_pct", "line"),
    },
    "resource-loading": {
        "metrics": [("Resources", "resources", "len"),
                    ("Unassigned activities", "unassigned_activities", None)],
        "tables": [("Resource inventory", "resources"), ("Resource histogram", "histogram")],
        "chart": ("histogram", "date", "quantity", "area"),
    },
    "sequence-coding": {
        "metrics": [("Stage coverage (%)", "proposal.stage_coverage_pct", None),
                    ("Front coverage (%)", "proposal.front_coverage_pct", None),
                    ("Mapped activities", "analysis.mapped_activities", None),
                    ("Analyst confirmed", "analysis.mapping_confirmed", None)],
        "tables": [("Mapping editor", "proposal.rows"), ("Sequence bands", "analysis.bands"),
                   ("Fronts by finish", "analysis.fronts_by_finish")],
        "warnings": ["proposal.warnings", "analysis.warnings"],
        "caveats": ["analysis.caveats"],
    },
    "hierarchy": {
        "metrics": [("Source activities", "hierarchy.source_activities", None),
                    ("Placed activities", "hierarchy.placed_activities", None),
                    ("Duplicate IDs", "hierarchy.duplicate_ids", None)],
        "tables": [("Available dimensions", "available_dimensions"),
                   ("Unassigned by level", "hierarchy.unassigned_per_level"),
                   ("Hierarchy tree", "tree.children")],
    },
    "milestone-shift": {
        "metrics": [("Milestones", "series", "len"),
                    ("Needs confirmation", "needs_confirmation", "len")],
        "tables": [("Milestone series", "series"),
                   ("Milestones needing confirmation", "needs_confirmation")],
    },
    "progress-transfer": {
        "metrics": [("Applied starts", "applied_starts", None),
                    ("Applied finishes", "applied_finishes", None),
                    ("Network effect (days)", "network_effect_days", None),
                    ("Scope effect (days)", "scope_effect_days", None),
                    ("Calibration (days)", "calibration_days", None)],
        "tables": [("Unmatched progress", "unmatched_progress"),
                   ("OOS flags", "oos_flags"), ("Milestones", "milestones"),
                   ("Driving chain", "driving_chain")],
    },
    "as-built-critical-path": {
        "metrics": [("Terminal", "terminal_code", None), ("Activities", "activities", "len"),
                    ("Hybrid path", "hybrid", None), ("Data date", "data_date", None)],
        "tables": [("Adoptable path", "activities"), ("Logic links", "links")],
    },
    "report-assembler": {
        "metrics": [("Included sections", "sections", None)],
        "tables": [("Included immutable runs", "included_runs")],
    },
    "as-planned-vs-as-built": {
        "metrics": [("Baseline", "baseline", None), ("As-built", "as_built", None),
                    ("Compared activities", "rows", "len")],
        "tables": [("Planned vs actual", "rows"),
                   ("RLPA ingestion", "rlpa.run.ingestion"),
                   ("Fitness gates", "rlpa.run.fitness.gates"),
                   ("Candidate interpretations", "rlpa.candidate_interpretations"),
                   ("Interruptions", "rlpa.interruption_interpretations"),
                   ("Analyst review items", "rlpa.review_items"),
                   ("Report sections", "rlpa.report_sections")],
    },
    "windows-analysis": {
        "metrics": [("Total movement (days)", "total_movement_days", None),
                    ("Windows", "windows", "len")],
        "tables": [("Time-slice windows and drivers", "windows")],
        "chart": ("windows", "to_label", "movement_days", "bar"),
    },
    "impacted-as-planned": {
        "metrics": [("Completion before", "completion_pre", None),
                    ("Completion after", "completion_final", None),
                    ("Impact (days)", "total_delta_days", None),
                    ("Events used", "events_used", None), ("Gated", "gated", None)],
        "tables": [("Event impacts", "rows"), ("Concurrency screening", "concurrency"),
                   ("Skipped events", "skipped_events")],
        "chart": ("rows", "event_id", "incremental_delta_days", "bar"),
    },
    "collapsed-as-built": {
        "metrics": [("As-built completion", "asbuilt_completion", None),
                    ("Collapsed completion", "collapsed_completion", None),
                    ("Measured impact (days)", "delta_days", None),
                    ("Calibration (days)", "calibration_days", None),
                    ("Decision grade", "decision_grade", None)],
        "tables": [("Removed activities", "removed_codes"),
                   ("Model chain", "model_chain"), ("Collapsed chain", "critical_chain")],
    },
    "time-impact-analysis": {
        "metrics": [("Data date", "data_date", None),
                    ("Completion before", "completion_pre", None),
                    ("Completion after", "completion_post", None),
                    ("Impact (days)", "completion_delta_days", None),
                    ("Calibration (days)", "calibration_days", None),
                    ("Decision grade", "decision_grade", None)],
        "tables": [("Fragnet editor", "fragnet"), ("Milestone impacts", "milestone_impacts"),
                   ("Pre-impact path", "path_pre"), ("Post-impact path", "path_post"),
                   ("Tie-in float", "tie_in_float")],
        "chart": ("milestone_impacts", "code", "float_post", "bar"),
    },
}


def _at(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _messages(value: Dict[str, Any], paths: Iterable[str]) -> List[str]:
    items: List[str] = []
    for path in paths:
        found = _at(value, path)
        if isinstance(found, list):
            items.extend(str(item) for item in found)
    return list(dict.fromkeys(items))


def build_module_view(module_slug: str, value: Dict[str, Any]) -> Tuple[
        List[Dict[str, Any]], List[Dict[str, Any]], List[str], List[str], Dict[str, Any] | None]:
    spec = MODULE_VIEW_SPECS[module_slug]
    metrics = []
    for label, path, operation in spec.get("metrics", []):
        found = _at(value, path)
        if operation == "len":
            found = len(found) if isinstance(found, (list, dict)) else 0
        metrics.append({"label": label, "value": found})
    tables = []
    for label, path in spec.get("tables", []):
        rows = _at(value, path)
        if isinstance(rows, dict):
            rows = [{"key": key, "value": child} for key, child in rows.items()]
        elif isinstance(rows, list) and rows and not isinstance(rows[0], dict):
            rows = [{"value": child} for child in rows]
        if not isinstance(rows, list):
            rows = []
        tables.append({"name": label, "rows": rows[:500], "total_rows": len(rows),
                       "truncated": len(rows) > 500})
    warnings = _messages(value, ["warnings", *spec.get("warnings", [])])
    caveats = _messages(value, ["caveats", *spec.get("caveats", [])])
    chart = None
    if spec.get("chart"):
        path, x_field, y_field, mark = spec["chart"]
        rows = _at(value, path)
        usable = [row for row in (rows or []) if isinstance(row, dict)
                  and row.get(x_field) is not None and row.get(y_field) is not None]
        if usable:
            temporal = "date" in x_field
            chart = {
                "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                "description": f"{module_slug}: {path}", "width": "container", "height": 300,
                "data": {"values": usable[:500]},
                "mark": {"type": mark, "tooltip": True, "point": mark == "line"},
                "encoding": {
                    "x": {"field": x_field, "type": "temporal" if temporal else "nominal",
                          "sort": None, "title": x_field.replace("_", " ").title()},
                    "y": {"field": y_field, "type": "quantitative",
                          "title": y_field.replace("_", " ").title()},
                },
                "config": {"background": "transparent", "view": {"stroke": "#d8d4ca"}},
            }
    return metrics, tables, warnings, caveats, chart


__all__ = ["MODULE_VIEW_SPECS", "build_module_view"]
