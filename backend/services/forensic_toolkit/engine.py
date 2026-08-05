"""UI-independent adapters around the pinned forensic toolkit engines.

This module never imports ``app.py``, ``views`` or Streamlit. Every public
module slug is mapped to a deterministic engine call and a stable COAir result
envelope suitable for persistence and React rendering.
"""

from __future__ import annotations

import dataclasses
import io
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List

from openpyxl import Workbook

from src.config import BASE_DIR
from src.forensic_store import UPSTREAM_SHA
from .presentation import build_module_view


VENDOR_ROOT = Path(BASE_DIR) / "vendor" / "delay-analysis-toolkit"
if str(VENDOR_ROOT) not in sys.path:
    sys.path.insert(0, str(VENDOR_ROOT))


MODULE_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "intake": {"title": "Data Intake", "group": "programme", "minimum_files": 1},
    "dcma": {"title": "DCMA 14-Point Assessment", "group": "programme", "minimum_files": 1},
    "baseline-critical-path": {"title": "Baseline Critical Path", "group": "programme", "minimum_files": 1},
    "revision-comparison": {"title": "Revision Comparison", "group": "programme", "minimum_files": 2},
    "out-of-sequence": {"title": "Out-of-Sequence Progress", "group": "programme", "minimum_files": 1},
    "float-erosion": {"title": "Float Erosion", "group": "programme", "minimum_files": 2},
    "progress-s-curve": {"title": "Progress S-Curve", "group": "programme", "minimum_files": 2},
    "resource-loading": {"title": "Resource Loading", "group": "programme", "minimum_files": 1},
    "sequence-coding": {"title": "Sequence Coding", "group": "programme", "minimum_files": 1},
    "hierarchy": {"title": "Hierarchy Rebuild", "group": "programme", "minimum_files": 1},
    "milestone-shift": {"title": "Milestone Shift", "group": "programme", "minimum_files": 2},
    "progress-transfer": {"title": "Progress Transfer", "group": "programme", "minimum_files": 2},
    "as-built-critical-path": {"title": "As-Built Critical Path", "group": "programme", "minimum_files": 1},
    "report-assembler": {"title": "Report Assembler", "group": "programme", "minimum_files": 1},
    "as-planned-vs-as-built": {"title": "As-Planned vs As-Built", "group": "retrospective", "minimum_files": 2},
    "windows-analysis": {"title": "Windows Analysis", "group": "retrospective", "minimum_files": 2},
    "impacted-as-planned": {"title": "Impacted As-Planned", "group": "retrospective", "minimum_files": 1},
    "collapsed-as-built": {"title": "Collapsed As-Built", "group": "retrospective", "minimum_files": 1},
    "time-impact-analysis": {"title": "Time Impact Analysis", "group": "prospective", "minimum_files": 1},
}


class ForensicEngineError(RuntimeError):
    pass


def json_safe(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {field.name: json_safe(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "value"):
        return json_safe(value.value)
    return str(value)


def _parse_programmes(programmes: List[Dict[str, Any]]):
    from dcma import parse_xer
    parsed = []
    for programme in programmes:
        path = Path(programme["file_path"])
        if not path.is_file():
            raise ForensicEngineError("forensic_source_missing")
        parsed.append((programme["name"], parse_xer(str(path))))
    from programme import build_inventory
    inventory = build_inventory(parsed)
    pool = dict(parsed)
    ordered = [(revision.file_name, pool[revision.file_name]) for revision in inventory.revisions]
    return ordered, inventory


def _select(ordered, index: int, default: int = -1):
    position = index if -len(ordered) <= index < len(ordered) else default
    return ordered[position]


def _events(parameters: Dict[str, Any]):
    from programme import event_from_dict
    records = []
    for raw in parameters.get("events", []):
        rebuilt = event_from_dict(raw)
        if rebuilt:
            records.append(rebuilt)
    return records


def _run_intake(ordered, inventory, _p):
    return inventory


def _run_dcma(ordered, _inventory, p):
    from dcma import DCMAConfig, annotate_path_position, build_dcma_trace, run_all_checks
    name, data = _select(ordered, int(p.get("programme_index", -1)))
    config = DCMAConfig()
    for key, value in p.get("thresholds", {}).items():
        if hasattr(config, key) and isinstance(value, (int, float, bool)):
            setattr(config, key, value)
    results = run_all_checks(data, config)
    trace = build_dcma_trace(data, config, results)
    annotate_path_position(results, trace)
    return {"programme": name, "checks": results, "trace": trace}


def _run_critical_path(ordered, _inventory, p):
    from programme import extract_critical_path, extract_longest_path
    name, data = _select(ordered, int(p.get("programme_index", 0)), 0)
    if p.get("method", "longest_path") == "float":
        return extract_critical_path(
            data, name, float_tolerance_days=float(p.get("float_tolerance_days", 0)),
            near_critical_days=float(p.get("near_critical_days", 10)),
        )
    return extract_longest_path(
        data, name, end_task_code=p.get("end_task_code") or None,
        near_critical_days=float(p.get("near_critical_days", 10)),
        branch_tolerance_hours=float(p.get("branch_tolerance_hours", 1)),
    )


def _run_comparison(ordered, _inventory, p):
    from programme import assess_comparison_impact, attribute_completion_impact, compare_revisions
    old_name, old = _select(ordered, int(p.get("old_index", 0)), 0)
    new_name, new = _select(ordered, int(p.get("new_index", -1)))
    comparison = compare_revisions(old, new, old_name, new_name)
    impact = assess_comparison_impact(old, new, old_name, new_name,
                                      comparison=comparison,
                                      end_task_code=p.get("end_task_code") or None)
    attribution = attribute_completion_impact(old, new, old_name, new_name,
                                              comparison=comparison, impact=impact,
                                              end_task_code=p.get("end_task_code") or None)
    return {"comparison": comparison, "impact": impact, "attribution": attribution}


def _run_oos(ordered, _inventory, p):
    from programme import build_repair_plan, oos_evolution, out_of_sequence_flags
    name, data = _select(ordered, int(p.get("programme_index", -1)))
    flags = out_of_sequence_flags(data)
    return {"programme": name, "flags": flags,
            "repair_plan": build_repair_plan(data, flags),
            "evolution": oos_evolution(ordered)}


def _run_float(ordered, _inventory, p):
    from programme import analyse_float_erosion
    return analyse_float_erosion(ordered, near_days=float(p.get("near_critical_days", 10)))


def _run_progress(ordered, inventory, p):
    from programme import compute_progress
    pool = dict(ordered)
    baseline_name = inventory.baseline.file_name if inventory.baseline else ordered[0][0]
    updates = [(name, data) for name, data in ordered if name != baseline_name]
    return compute_progress(pool[baseline_name], baseline_name, updates,
                            weight_scheme=p.get("weight_scheme", "duration"))


def _run_resources(ordered, _inventory, p):
    from programme import extract_resource_loading
    name, data = _select(ordered, int(p.get("programme_index", 0)), 0)
    return extract_resource_loading(data, name)


def _run_sequence(ordered, _inventory, p):
    from programme import analyse_sequence, propose_sequence_mapping
    name, data = _select(ordered, int(p.get("programme_index", -1)))
    proposal = propose_sequence_mapping(data, name)
    return {"proposal": proposal,
            "analysis": analyse_sequence(proposal.rows, name,
                                         mapping_confirmed=bool(p.get("mapping_confirmed", False)),
                                         min_front_activities=int(p.get("min_front_activities", 3)))}


def _run_hierarchy(ordered, _inventory, p):
    from programme import available_dimensions, build_hierarchy, tree_to_dict
    name, data = _select(ordered, int(p.get("programme_index", -1)))
    available = available_dimensions(data)
    requested = list(p.get("dimension_ids") or [])
    dimension_ids = requested or [d.dim_id for d in available[:2]]
    result = build_hierarchy(data, dimension_ids, name)
    return {"available_dimensions": available, "hierarchy": result,
            "tree": tree_to_dict(result.root) if result.root else None}


def _run_milestones(ordered, inventory, _p):
    from programme import track_milestone_shifts
    pool = dict(ordered)
    revisions = [(r.label, r.data_date, pool[r.file_name])
                 for r in inventory.revisions if r.data_date is not None]
    return track_milestone_shifts(revisions)


def _run_transfer(ordered, _inventory, p):
    from programme import run_progress_transfer
    network_name, network = _select(ordered, int(p.get("network_index", 0)), 0)
    progress_name, progress = _select(ordered, int(p.get("progress_index", -1)))
    return run_progress_transfer(network, progress, network_name, progress_name)


def _run_asbuilt(ordered, _inventory, p):
    from programme import extract_actual_trace
    return extract_actual_trace(
        ordered, end_task_code=p.get("end_task_code") or None,
        max_gap_days=float(p.get("max_gap_days", 15)),
        allow_temporal_fallback=bool(p.get("allow_temporal_fallback", True)),
        allow_forecast_tail=bool(p.get("allow_forecast_tail", True)),
    )


def _run_apab(ordered, inventory, p):
    from programme import extract_asbuilt_longest_path, planned_vs_actual
    pool = dict(ordered)
    baseline_name = inventory.baseline.file_name if inventory.baseline else ordered[0][0]
    latest_name, latest = ordered[-1]
    rows = planned_vs_actual(pool[baseline_name], latest, p.get("activity_codes") or None,
                             date_basis=p.get("date_basis", "late"))
    from rlpa_apvab_v2.adapter import load_xer_snapshot
    from rlpa_apvab_v2.engine import analyse
    from rlpa_apvab_v2.graph import primitive
    from rlpa_apvab_v2.reporting import html_report, report_sections
    snapshots = [load_xer_snapshot(path) for path in p.get("_source_paths", [])]
    rlpa = analyse(snapshots, anchor_task_code=p.get("end_task_code") or None)
    from path_studio import PathDraft, build_path_studio_html, dataset_from_xer, validate_draft
    candidate = extract_asbuilt_longest_path(latest)
    path_codes = tuple(activity.task_code for activity in candidate.activities)
    dataset = dataset_from_xer(
        latest, path_codes=path_codes, basis="as-built longest path",
        milestone_code=candidate.terminal_code or "", baseline=pool[baseline_name],
        date_basis=p.get("date_basis", "target"),
    )
    draft = PathDraft(analysis_id=dataset.analysis_id, path_codes=path_codes,
                      basis="as-built longest path")
    return {
        "baseline": baseline_name, "as_built": latest_name, "rows": rows,
        "rlpa": {
            "run": primitive(rlpa.run),
            "candidate_interpretations": primitive(rlpa.candidate_interpretations),
            "interruption_interpretations": primitive(rlpa.interruption_interpretations),
            "review_items": primitive(rlpa.review_items),
            "report_sections": primitive(report_sections(rlpa)),
        },
        "_rlpa_html": html_report(rlpa),
        "_path_studio_html": build_path_studio_html(
            dataset, draft, validate_draft(dataset, draft),
        ),
    }


def _run_windows(ordered, _inventory, p):
    from programme import analyse_windows
    return analyse_windows(
        ordered, end_task_code=p.get("end_task_code") or None,
        switch_threshold=float(p.get("switch_threshold", .5)),
        bifurcate=bool(p.get("bifurcate", True)),
    )


def _run_iap(ordered, inventory, p):
    from programme import run_impacted_asplanned
    pool = dict(ordered)
    baseline_name = inventory.baseline.file_name if inventory.baseline else ordered[0][0]
    return run_impacted_asplanned(pool[baseline_name], baseline_name, _events(p))


def _run_cab(ordered, _inventory, p):
    from programme import collapse_asbuilt
    name, data = _select(ordered, int(p.get("programme_index", -1)))
    return collapse_asbuilt(data, name, set(p.get("remove_activity_codes") or []),
                            anchor_code=p.get("anchor_code") or None)


def _run_tia(ordered, _inventory, p):
    from programme import run_tia
    records = _events(p)
    if not records:
        raise ForensicEngineError("forensic_event_required")
    name, data = _select(ordered, int(p.get("programme_index", -1)))
    event, fragnet = records[0]
    return run_tia(data, name, event, fragnet,
                   target_milestone=p.get("target_milestone") or None)


_RUNNERS: Dict[str, Callable] = {
    "intake": _run_intake, "dcma": _run_dcma,
    "baseline-critical-path": _run_critical_path,
    "revision-comparison": _run_comparison, "out-of-sequence": _run_oos,
    "float-erosion": _run_float, "progress-s-curve": _run_progress,
    "resource-loading": _run_resources, "sequence-coding": _run_sequence,
    "hierarchy": _run_hierarchy, "milestone-shift": _run_milestones,
    "progress-transfer": _run_transfer, "as-built-critical-path": _run_asbuilt,
    "as-planned-vs-as-built": _run_apab, "windows-analysis": _run_windows,
    "impacted-as-planned": _run_iap, "collapsed-as-built": _run_cab,
    "time-impact-analysis": _run_tia,
}


def _report_manifest_xlsx(title: str, full: Dict[str, Any]) -> bytes:
    wb = Workbook()
    sheet = wb.active
    sheet.title = "Report Manifest"
    sheet.append([title])
    sheet.append([])
    sheet.append(["Included run ID"])
    for run_id in full.get("included_run_ids") or []:
        sheet.append([run_id])
    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def _report_docx(title: str, prior_runs: List[Dict[str, Any]], programmes,
                 inventory, parameters: Dict[str, Any]) -> bytes:
    """Render with the canonical upstream Report Assembler.

    It consumes the actual immutable runs and analyst workspace decisions;
    module calculations are never recomputed with default parameters here.
    """
    from programme import BasisOfAnalysis, ReportSection, SourceFile, build_assembled_report

    workspace_state = parameters.get("_workspace_state") or {}
    report_state = workspace_state.get("report") or {}
    selected = set(report_state.get("selected_sections") or [])
    narratives = workspace_state.get("narratives") or {}
    sections = []
    for run in reversed(prior_runs):
        slug = str(run.get("module_slug") or "")
        if slug == "report-assembler" or (selected and slug not in selected):
            continue
        result = run.get("result") or {}
        narrative_record = narratives.get(slug) or {}
        narrative = (narrative_record.get("text") if isinstance(narrative_record, dict)
                     else str(narrative_record or "")) or result.get("narrative")
        findings = [f"{metric.get('label')}: {metric.get('value')}"
                    for metric in result.get("metrics", [])
                    if metric.get("value") is not None]
        images = []
        if report_state.get("include_charts", True) and result.get("chart"):
            try:
                import vl_convert as vlc
                images.append((
                    vlc.vegalite_to_png(json.dumps(result["chart"]), scale=2),
                    f"{MODULE_DEFINITIONS.get(slug, {}).get('title', slug)} chart",
                ))
            except Exception:
                # Chart rendering is supplementary; deterministic tables and
                # caveats must remain exportable if rasterisation fails.
                pass
        sections.append(ReportSection(
            title=MODULE_DEFINITIONS.get(slug, {}).get("title", slug),
            narrative_md=narrative or None,
            key_findings=findings,
            caveats=[str(item) for item in (
                list(result.get("warnings") or []) + list(result.get("caveats") or [])
            )], images=images,
        ))

    hashes = {item["name"]: item.get("sha256", "not recorded") for item in programmes}
    files = []
    for revision in inventory.revisions:
        files.append(SourceFile(
            file_name=revision.file_name,
            sha256=hashes.get(revision.file_name, "not recorded"),
            data_date=revision.data_date,
            role=("Baseline" if revision.is_baseline else
                  "Current" if revision.is_current else "Update"),
            activity_count=revision.activity_count,
        ))
    settings = [
        f"COAir source revision — {parameters.get('_source_revision', 'not recorded')}",
        f"Delay Analysis Toolkit upstream commit — {UPSTREAM_SHA}",
        f"Workspace state version — {parameters.get('_state_version', 'not recorded')}",
    ]
    for source in parameters.get("_workspace_sources") or []:
        if source.get("source_kind") != "programme":
            settings.append(
                f"Evidence — {source.get('file_name')}: SHA-256 {source.get('content_hash')}"
            )
    for module, lines in sorted((workspace_state.get("analysis_basis") or {}).items()):
        settings.extend(f"{module} — {line}" for line in lines)
    basis = BasisOfAnalysis(files=files, settings=settings)
    return build_assembled_report(
        report_state.get("title") or title,
        report_state.get("project") or "",
        report_state.get("prepared_by") or "",
        sections,
        basis,
    )


def _upstream_xlsx(module_slug: str, raw: Any, ordered, inventory,
                   parameters: Dict[str, Any]) -> bytes:
    """Use the upstream report engine wherever it defines the export."""
    from programme import (
        build_asbuilt_xlsx, build_comparison_xlsx, build_critical_path_xlsx,
        build_float_erosion_xlsx, build_hierarchy_xlsx, build_iap_xlsx,
        build_inventory_xlsx, build_milestone_xlsx, build_oos_xlsx,
        build_progress_xlsx, build_resources_xlsx, build_sequence_xlsx,
        build_simple_xlsx, build_tia_xlsx, build_transfer_xlsx,
        build_windows_xlsx,
    )
    if module_slug == "intake":
        return build_inventory_xlsx(raw)
    if module_slug == "dcma":
        from dcma.report_xlsx import build_xlsx_report
        _, data = _select(ordered, int(parameters.get("programme_index", -1)))
        return build_xlsx_report(data, raw["checks"], trace=raw["trace"])
    if module_slug == "baseline-critical-path":
        return build_critical_path_xlsx(raw)
    if module_slug == "revision-comparison":
        return build_comparison_xlsx(raw["comparison"], impact=raw["impact"],
                                     attribution=raw["attribution"])
    if module_slug == "out-of-sequence":
        return build_oos_xlsx(raw["programme"], raw["flags"], raw["repair_plan"],
                              evolution=raw["evolution"])
    if module_slug == "float-erosion":
        return build_float_erosion_xlsx(raw)
    if module_slug == "progress-s-curve":
        return build_progress_xlsx(raw)
    if module_slug == "resource-loading":
        return build_resources_xlsx(raw)
    if module_slug == "sequence-coding":
        return build_sequence_xlsx(raw["analysis"], raw["proposal"].rows)
    if module_slug == "hierarchy":
        return build_hierarchy_xlsx(raw["hierarchy"])
    if module_slug == "milestone-shift":
        return build_milestone_xlsx(raw, raw.series)
    if module_slug == "progress-transfer":
        return build_transfer_xlsx(raw)
    if module_slug == "as-built-critical-path":
        return build_asbuilt_xlsx(raw)
    if module_slug == "windows-analysis":
        return build_windows_xlsx(raw)
    if module_slug == "impacted-as-planned":
        baseline_name = inventory.baseline.file_name if inventory.baseline else ordered[0][0]
        return build_iap_xlsx(baseline_name, raw)
    if module_slug == "time-impact-analysis":
        return build_tia_xlsx(raw)
    safe = json_safe(raw)
    if module_slug == "as-planned-vs-as-built":
        return build_simple_xlsx("As-Planned vs As-Built", {"Activities": safe["rows"]})
    if module_slug == "collapsed-as-built":
        return build_simple_xlsx(
            "Collapsed As-Built",
            {"Model chain": safe.get("model_chain", []),
             "Collapsed chain": safe.get("critical_chain", [])},
            notes=safe.get("warnings", []) + safe.get("caveats", []),
        )
    raise KeyError(module_slug)


def run_module(module_slug: str, programmes: List[Dict[str, Any]],
               parameters: Dict[str, Any], *, prior_runs: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    if module_slug not in MODULE_DEFINITIONS:
        raise ForensicEngineError("forensic_module_unsupported")
    definition = MODULE_DEFINITIONS[module_slug]
    if len(programmes) < int(definition["minimum_files"]):
        raise ForensicEngineError("forensic_programmes_insufficient")

    ordered, inventory = _parse_programmes(programmes)
    engine_parameters = dict(parameters)
    engine_parameters["_source_paths"] = [programme["file_path"] for programme in programmes]
    if module_slug == "report-assembler":
        document = _report_docx(
            parameters.get("report_title") or "Forensic Programme Analysis",
            prior_runs or [], programmes, inventory, parameters,
        )
        raw_result: Any = {"sections": len(prior_runs or []),
                           "included_run_ids": [r["run_id"] for r in prior_runs or []],
                           "included_runs": [{"run_id": r["run_id"],
                                              "module": r["module_slug"],
                                              "source_revision": r["source_revision"]}
                                             for r in prior_runs or []]}
        special_artifacts = [{"kind": "word", "name": "forensic-programme-analysis.docx",
                              "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                              "content": document}]
    else:
        raw_result = _RUNNERS[module_slug](ordered, inventory, engine_parameters)
        special_artifacts = []
        if (module_slug == "out-of-sequence" and parameters.get("build_repaired_xer")
                and raw_result.get("repair_plan")):
            from programme import apply_asbuilt_repairs
            selected_name, selected_data = _select(
                ordered, int(parameters.get("programme_index", -1)),
            )
            allowed = set(parameters.get("repair_activity_pairs") or [])
            for repair in raw_result["repair_plan"]:
                pair = f"{repair.pred_code}->{repair.succ_code}"
                repair.apply = bool(not allowed or pair in allowed) and not repair.blocked
            source = next(item for item in programmes if item["name"] == selected_name)
            repaired, repair_report = apply_asbuilt_repairs(
                Path(source["file_path"]).read_bytes(), selected_data,
                raw_result["repair_plan"],
            )
            raw_result["repair_report"] = repair_report
            if repair_report.qa_passed:
                special_artifacts.append({
                    "kind": "xer", "name": Path(selected_name).stem + "_asbuilt_repair.xer",
                    "mime_type": "application/octet-stream",
                    "content": repaired.encode("latin-1", "replace"),
                })
        if module_slug == "time-impact-analysis":
            from programme import build_impacted_xer
            selected_name, selected_data = _select(
                ordered, int(parameters.get("programme_index", -1)),
            )
            records = _events(engine_parameters)
            if records:
                _event, fragnet = records[0]
                source = next(item for item in programmes if item["name"] == selected_name)
                impacted = build_impacted_xer(
                    Path(source["file_path"]).read_bytes().decode("utf-8", errors="replace"),
                    selected_data, fragnet, raw_result,
                )
                special_artifacts.append({
                    "kind": "xer",
                    "name": f"impacted_{_event.event_id}_{Path(selected_name).name}",
                    "mime_type": "application/octet-stream",
                    "content": impacted.encode("utf-8"),
                })
        if module_slug == "as-planned-vs-as-built":
            rlpa_html = raw_result.pop("_rlpa_html")
            path_studio_html = raw_result.pop("_path_studio_html")
            special_artifacts.append({
                "kind": "html", "name": "rlpa-apvab-v2.html",
                "mime_type": "text/html", "content": rlpa_html.encode("utf-8"),
            })
            special_artifacts.append({
                "kind": "html", "name": "path-studio.html",
                "mime_type": "text/html", "content": path_studio_html.encode("utf-8"),
            })
        if module_slug == "baseline-critical-path":
            from programme import build_gantt_html, group_tree
            def activity_row(activity):
                return {
                    "id": activity.task_code, "name": activity.name,
                    "start": activity.early_start or activity.early_finish,
                    "finish": activity.early_finish or activity.early_start,
                    "milestone": activity.is_milestone, "status": activity.band,
                }
            groups = [{"name": "Critical path", "activities": [
                activity_row(activity) for activity in raw_result.critical
                if activity.early_start or activity.early_finish
            ]}]
            near = [activity_row(activity) for activity in raw_result.near_critical
                    if activity.early_start or activity.early_finish]
            if near:
                groups.append({"name": "Near-critical band", "activities": near})
            data_date = (ordered[0][1].project.data_date.isoformat()
                         if ordered[0][1].project and ordered[0][1].project.data_date else None)
            html = build_gantt_html(group_tree(groups), data_date=data_date,
                                    title=f"Critical path — {ordered[0][0]}")
            special_artifacts.append({"kind": "html", "name": "critical-path.html",
                                      "mime_type": "text/html", "content": html.encode("utf-8")})
        elif module_slug == "hierarchy" and raw_result.get("tree"):
            from programme import build_gantt_html
            selected_name, selected_data = _select(
                ordered, int(parameters.get("programme_index", -1)),
            )
            data_date = (selected_data.project.data_date.isoformat()
                         if selected_data.project and selected_data.project.data_date else None)
            html = build_gantt_html(raw_result["tree"], data_date=data_date,
                                    title=f"Hierarchy — {selected_name}")
            special_artifacts.append({"kind": "html", "name": "hierarchy-gantt.html",
                                      "mime_type": "text/html", "content": html.encode("utf-8")})

    full = json_safe(raw_result)
    if not isinstance(full, dict):
        full = {"value": full}
    metrics, public_tables, warnings, caveats, chart = build_module_view(module_slug, full)
    payload = {
        "title": definition["title"], "module": module_slug,
        "metrics": metrics, "tables": public_tables,
        "warnings": warnings[:100], "caveats": caveats[:100],
        "source_programmes": [{k: p[k] for k in ("file_id", "name", "sha256")}
                              for p in programmes],
        "chart": chart,
    }
    json_bytes = json.dumps(full, ensure_ascii=False, indent=2).encode("utf-8")
    if module_slug == "report-assembler":
        spreadsheet = _report_manifest_xlsx(definition["title"], full)
    else:
        spreadsheet = _upstream_xlsx(module_slug, raw_result, ordered, inventory, engine_parameters)
    payload["_artifacts"] = special_artifacts + [
        {"kind": "json", "name": f"{module_slug}.json", "mime_type": "application/json",
         "content": json_bytes},
        {"kind": "excel", "name": f"{module_slug}.xlsx",
         "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         "content": spreadsheet},
    ]
    return payload


__all__ = ["ForensicEngineError", "MODULE_DEFINITIONS", "VENDOR_ROOT",
           "json_safe", "run_module"]
