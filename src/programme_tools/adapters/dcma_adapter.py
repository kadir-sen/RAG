"""programme.dcma_14_point adapter — deterministic schedule health scorecard."""

from __future__ import annotations

from typing import Any, Dict, List

from ..schemas import AdapterOutput, ArtifactBlob, ToolResult, json_safe
from .xer_loader import load_xer_files

TOOL_ID = "programme.dcma_14_point"

_AFFECTED_SHOWN = 25


def run(records: List[Dict[str, Any]]) -> AdapterOutput:
    """Run the 14 DCMA checks on exactly ONE XER file (the handler enforces
    single-file input and asks the user to pick when several are in scope)."""
    from ..vendor.dcma import run_all_checks
    from ..vendor.dcma.config import DCMAConfig
    from ..vendor.dcma.report_xlsx import build_xlsx_report

    (file_name, data), = load_xer_files(records[:1])
    results = run_all_checks(data, DCMAConfig())

    rows = []
    for r in results:
        affected = ", ".join(r.affected_ids[:_AFFECTED_SHOWN])
        if len(r.affected_ids) > _AFFECTED_SHOWN:
            affected += f" (+{len(r.affected_ids) - _AFFECTED_SHOWN} more)"
        rows.append([
            r.number, r.name, r.status.value,
            f"{r.metric_label} = {r.metric_value}", r.threshold,
            r.summary if not r.na_reason else f"N/A: {r.na_reason}",
            affected or "—",
        ])
    tables = [{
        "title": f"DCMA 14-Point scorecard — {file_name}",
        "columns": ["#", "Check", "Status", "Metric", "Target", "Finding",
                    "Affected activities"],
        "rows": rows,
    }]

    n_pass = sum(1 for r in results if r.status.value == "PASS")
    n_fail = sum(1 for r in results if r.status.value == "FAIL")
    n_na = sum(1 for r in results if r.status.value == "N/A")
    summary = (f"DCMA 14-point on {file_name}: {n_pass} pass / {n_fail} fail / "
               f"{n_na} N/A.")

    caveats = [
        "DCMA thresholds are screening guidance, not contractual standards; "
        "failed checks indicate areas for review, not proven defects.",
    ]

    result = ToolResult(
        tool_id=TOOL_ID,
        summary=summary,
        tables=tables,
        caveats=caveats,
        raw={"file_name": file_name, "checks": json_safe(results)},
    )
    # Engine objects for the narrative prompt builders (not serialized).
    result._engine_ctx = {"data": data, "results": results}
    blobs = [ArtifactBlob(f"dcma_scorecard_{_safe_stem(file_name)}.xlsx", "xlsx",
                          build_xlsx_report(data, results))]
    return result, blobs


def _safe_stem(file_name: str) -> str:
    stem = file_name.rsplit(".", 1)[0]
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)[:60]
