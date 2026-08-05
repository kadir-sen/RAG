"""Versioned native-UI contract derived from the pinned Streamlit views.

This is intentionally explicit: an upstream UI change must alter this manifest
or fail the fingerprint test instead of silently disappearing behind a generic
form.  Labels are user-facing and remain English to match the toolkit.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict


PARITY_VERSION = "forensic-parity-v1"


def _control(name: str, label: str, kind: str, **values: Any) -> Dict[str, Any]:
    return {"name": name, "label": label, "kind": kind, **values}


MODULE_PARITY: Dict[str, Dict[str, Any]] = {
    "intake": {
        "steps": ["Project sources", "Programme roles", "Inventory & custody"],
        "controls": [
            _control("source_ids", "Project sources", "source_picker", required=True),
            _control("baseline_programme_id", "Contract baseline", "programme_select"),
            _control("contract_completion_milestone", "Contractual completion milestone", "activity_select"),
            _control("missing_inputs", "Missing inputs", "editable_list"),
        ],
        "actions": ["save_sources", "build_inventory", "load_bundled_sample", "export_custody"],
        "artifacts": ["inventory.xlsx", "custody-register.xlsx"],
    },
    "dcma": {
        "controls": [
            _control("programme_index", "Programme to assess", "programme_select", default=-1),
            _control("customise", "Revise DCMA thresholds", "toggle", default=False),
            *[_control(name, label, kind, default=default) for name, label, kind, default in (
                ("logic_max_pct", "1 · Max missing-logic %", "number", 5.0),
                ("leads_max_count", "2 · Max leads (count)", "number", 0),
                ("lags_max_pct", "3 · Max lags %", "number", 5.0),
                ("fs_min_pct", "4 · Min Finish-to-Start %", "number", 90.0),
                ("default_hours_per_day", "Fallback hours/day", "number", 8.0),
                ("strict_constraints", "Strict hard-constraint set", "toggle", True),
                ("hard_constraint_max_pct", "5 · Max hard-constraint %", "number", 5.0),
                ("high_float_days", "6 · High-float threshold (days)", "number", 44.0),
                ("high_float_max_pct", "6 · Max high-float %", "number", 5.0),
                ("negative_float_max_count", "7 · Max negative-float count", "number", 0),
                ("high_duration_days", "8 · High-duration threshold (days)", "number", 44.0),
                ("high_duration_max_pct", "8 · Max high-duration %", "number", 5.0),
                ("missed_tasks_max_pct", "11 · Max missed-tasks %", "number", 5.0),
                ("cpli_min", "13 · Minimum CPLI", "number", 0.95),
                ("bei_min", "14 · Minimum BEI", "number", 0.95),
                ("loe_driving_max_count", "15 · Max driving LOE count", "number", 0),
                ("redundant_max_pct", "16 · Max redundant-logic %", "number", 5.0),
                ("dangling_max_pct", "17 · Max dangling-activity %", "number", 5.0),
            )],
        ],
        "actions": ["run", "generate_narrative", "export_excel"],
        "views": ["scorecard", "check_details", "forensic_traceback", "basis", "caveats"],
    },
    "baseline-critical-path": {
        "controls": [
            _control("programme_index", "Programme", "programme_select", default=0),
            _control("method", "Identification method", "radio", default="longest_path",
                     options=["longest_path", "float"]),
            _control("end_task_code", "Trace backward from", "activity_select"),
            _control("near_critical_days", "Near-critical ≤ (days)", "number", default=10),
            _control("float_tolerance_days", "Critical float ≤ (days)", "number", default=0),
            _control("branch_tolerance_hours", "Driving-DAG branch tolerance (hours)", "number", default=1),
            _control("show_near_critical", "Show near-critical", "toggle", default=False),
            _control("contract_milestone", "Treat as contractual completion milestone", "toggle", default=False),
        ],
        "actions": ["run", "save_contract_milestone", "generate_narrative", "export_excel"],
        "views": ["metrics", "linked_gantt", "path_table", "basis", "caveats"],
    },
    "revision-comparison": {
        "controls": [
            _control("old_index", "Earlier revision", "programme_select", default=0),
            _control("new_index", "Later revision", "programme_select", default=-1),
            _control("end_task_code", "Completion milestone", "activity_select"),
            _control("impact_screening", "Run impact screening", "toggle", default=True),
            _control("provenance", "Build provenance timeline", "toggle", default=True),
        ],
        "actions": ["run", "generate_narrative", "export_comparison", "export_impact"],
        "views": ["completion_bridge", "materiality", "attribution", "driving_path", "provenance"],
    },
    "out-of-sequence": {
        "controls": [
            _control("programme_index", "Programme to screen", "programme_select", default=-1),
            _control("repair_rows", "As-built repair plan", "data_editor"),
            _control("build_repaired_xer", "Build repaired XER", "toggle", default=False),
        ],
        "actions": ["run", "save_repair_plan", "export_excel", "export_repaired_xer"],
        "views": ["flags", "repair_plan", "evolution", "caveats"],
    },
    "float-erosion": {
        "controls": [_control("near_critical_days", "Near-critical threshold (days)", "number", default=10)],
        "actions": ["run", "generate_narrative", "export_excel"],
        "views": ["trajectory_chart", "activity_movements", "caveats"],
    },
    "progress-s-curve": {
        "controls": [_control("weight_scheme", "Progress weighting", "radio", default="duration",
                              options=["duration", "count", "resource_qty"])],
        "actions": ["run", "generate_narrative", "export_excel"],
        "views": ["s_curve", "revision_table", "caveats"],
    },
    "resource-loading": {
        "controls": [
            _control("programme_index", "Programme", "programme_select", default=-1),
            _control("resource_ids", "Resources to chart", "multiselect"),
        ],
        "actions": ["run", "generate_narrative", "export_excel"],
        "views": ["resource_chart", "resource_table", "caveats"],
    },
    "sequence-coding": {
        "controls": [
            _control("programme_index", "Programme", "programme_select", default=-1),
            _control("review_scope", "Rows to review", "radio", default="unclassified"),
            _control("mapping_rows", "Construction sequence mapping", "data_editor"),
            _control("min_front_activities", "Minimum activities per front", "number", default=3),
        ],
        "actions": ["propose_mapping", "ai_review", "save_mapping", "confirm_mapping",
                    "recommend_view", "run", "generate_narrative", "export_excel"],
        "views": ["mapping_editor", "review_rounds", "sequence_gantt", "front_stage_matrix", "caveats"],
    },
    "hierarchy": {
        "controls": [
            _control("programme_index", "Programme", "programme_select", default=-1),
            _control("structure", "Structure", "radio", default="programme"),
            _control("dimension_ids", "Hierarchy levels", "multiselect"),
            _control("configuration_name", "Configuration name", "text"),
        ],
        "actions": ["run", "save_configuration", "apply_configuration", "export_excel"],
        "views": ["dimension_inventory", "tree_preview", "hierarchy_gantt"],
    },
    "milestone-shift": {
        "controls": [
            _control("milestone_ids", "Milestones to plot", "multiselect"),
            _control("y_axis", "Y-axis", "radio", default="forecast_date"),
        ],
        "actions": ["run", "generate_narrative", "export_excel"],
        "views": ["shift_chart", "milestone_table", "caveats"],
    },
    "progress-transfer": {
        "controls": [
            _control("network_index", "Network programme", "programme_select", default=0),
            _control("progress_index", "Progress source", "programme_select", default=-1),
            _control("enabled", "Run progress transfer", "toggle", default=False),
        ],
        "actions": ["run", "export_excel"],
        "views": ["transfer_summary", "statusing_choices", "oos_flags", "caveats"],
    },
    "as-built-critical-path": {
        "steps": ["Elect milestones", "Compare candidates", "Edit and adopt",
                  "Group umbrellas", "Review logic and report"],
        "controls": [
            _control("milestones", "Milestone(s) to measure to", "multiselect"),
            _control("candidate_basis", "As-built CP basis", "radio"),
            _control("path_codes", "Hand-edit the path", "multiselect"),
            _control("umbrella_rows", "Umbrella work packages", "data_editor"),
        ],
        "actions": ["compute_candidates", "adopt_path", "propose_umbrellas", "save_umbrellas",
                    "run", "generate_narrative", "export_excel"],
        "views": ["candidate_comparison", "divergence", "linked_gantt", "logic_links", "path_table"],
    },
    "report-assembler": {
        "controls": [
            _control("report_title", "Report title", "text", default="Preliminary Delay Analysis Report"),
            _control("project", "Project", "text"),
            _control("prepared_by", "Prepared by", "text"),
            _control("selected_sections", "Sections to include", "multiselect"),
            _control("regenerate", "Regenerate existing narratives", "toggle", default=False),
            _control("include_charts", "Embed module charts", "toggle", default=True),
        ],
        "actions": ["generate_missing_narratives", "assemble", "download_word"],
        "views": ["section_inventory", "narrative_status", "basis_preview"],
    },
    "as-planned-vs-as-built": {
        "steps": ["① Define as-built critical path", "② As-planned vs as-built",
                  "③ Windows", "④ Gantt & report"],
        "controls": [
            _control("milestones", "Trace to elected completion milestone", "multiselect"),
            _control("candidate_basis", "Adopt as the as-built critical path", "radio"),
            _control("date_basis", "Planned dates from the baseline", "radio", default="late"),
            _control("key_dates", "Analyst key dates", "data_editor"),
        ],
        "actions": ["infer_paths", "adopt_path", "save_key_dates", "run",
                    "generate_narrative", "export_excel"],
        "views": ["candidate_paths", "path_studio", "variance", "keydate_windows", "dual_gantt"],
    },
    "windows-analysis": {
        "controls": [
            _control("end_task_code", "Completion milestone", "activity_select"),
            _control("window_index", "Window to decompose", "select"),
        ],
        "actions": ["run", "generate_narrative", "export_excel", "run_concurrency", "run_explain"],
        "views": ["completion_trajectory", "movement_chart", "decomposition", "drivers", "path_changes"],
        "submodules": ["concurrency", "explain"],
    },
    "impacted-as-planned": {
        "controls": [
            _control("programme_index", "Baseline programme", "programme_select", default=0),
            _control("events", "Delay events and fragnets", "data_editor"),
            _control("use_event_register", "Use shared event register", "toggle", default=True),
        ],
        "actions": ["save_events", "run", "export_excel", "run_concurrency", "run_explain"],
        "views": ["event_register", "impact_results", "caveats"],
        "submodules": ["concurrency", "explain"],
    },
    "collapsed-as-built": {
        "steps": ["① Identify event groups", "② Validate extraction", "③ Collapse and compare"],
        "controls": [
            _control("programme_index", "As-built programme", "programme_select", default=-1),
            _control("group_query", "Activity name contains", "text"),
            _control("groups", "Candidate event groups", "editable_list"),
            _control("remove_activity_codes", "Activities to extract", "multiselect"),
            _control("override_validation", "Override validation gap", "toggle", default=False),
        ],
        "actions": ["propose_groups", "save_groups", "validate", "run", "export_excel",
                    "run_concurrency", "run_explain"],
        "views": ["group_candidates", "validation", "model_vs_collapsed", "controlling_chains"],
        "submodules": ["concurrency", "explain"],
    },
    "time-impact-analysis": {
        "steps": ["① Select Update & Connect AI", "② Register Event",
                  "③ Generate & Review Fragnet", "④ Recommend & Validate Logic",
                  "⑤ Run Time Impact", "⑥ Review & Explain Results",
                  "⑦ Export Report & Audit Trail"],
        "controls": [
            _control("programme_index", "Current accepted update", "programme_select", default=-1),
            _control("evidence_source_ids", "Project evidence documents", "source_picker"),
            _control("events", "Event register", "data_editor"),
            _control("contract_extract", "Contract extract", "text_area"),
            _control("fragnet_builder", "Builder", "radio", default="chain"),
            _control("fragnet", "Fragnet activities and relationships", "data_editor"),
            _control("target_milestone", "Target milestone", "activity_select"),
            _control("validation_checks", "Planner confirmations", "checklist"),
        ],
        "actions": ["extract_events", "save_event", "extract_clause", "recommend_fragnet",
                    "recommend_logic", "validate_fragnet", "run", "run_cumulative",
                    "generate_narrative", "export_excel", "export_impacted_xer",
                    "run_concurrency", "run_explain"],
        "views": ["health_gateway", "event_register", "comparable_activities", "fragnet_gantt",
                  "validation", "pre_post_comparison", "cumulative_impact", "audit_trail"],
        "submodules": ["concurrency", "explain"],
    },
}


def parity_fingerprint() -> str:
    return hashlib.sha256(json.dumps(
        MODULE_PARITY, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


__all__ = ["MODULE_PARITY", "PARITY_VERSION", "parity_fingerprint"]
