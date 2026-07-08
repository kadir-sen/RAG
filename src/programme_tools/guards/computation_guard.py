"""Computation Guard — pure-Python validation around tool execution.

No LLM anywhere in this module. Pre-execution failures become user-facing
clarifications or failed ToolResults; post-execution violations downgrade the
result to "partial" and force the analyst-review flag. A partial/failed
result is never upgraded afterwards.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from ..schemas import STATUS_COMPLETE, STATUS_PARTIAL, STATUSES, ToolResult

logger = logging.getLogger(__name__)


def validate_inputs(records: List[Dict[str, Any]]) -> List[str]:
    """Record-level pre-checks (cheap; parse-level checks live in xer_loader).

    Returns a list of user-safe problem strings; empty means OK.
    """
    problems: List[str] = []
    if not records:
        problems.append("No programme (.xer) files are available for this analysis.")
        return problems
    for rec in records:
        name = rec.get("file_name") or "unknown"
        if not str(name).lower().endswith(".xer"):
            problems.append(f"'{name}' is not a .xer programme file.")
            continue
        status = rec.get("status")
        if status not in (None, "completed"):
            problems.append(f"'{name}' has not finished processing (status: {status}).")
            continue
        path = rec.get("file_path") or ""
        p = Path(path)
        if not path or not p.exists():
            problems.append(f"'{name}' is missing on disk; please re-upload it.")
        elif p.stat().st_size == 0:
            problems.append(f"'{name}' is empty; please re-upload it.")
    return problems


def validate_result(result: ToolResult) -> ToolResult:
    """Post-execution contract checks. Violations downgrade, never raise."""
    violations: List[str] = []

    if result.status not in STATUSES:
        violations.append(f"invalid status '{result.status}'")
        result.status = STATUS_PARTIAL

    # Schema validity: the whole result must survive JSON round-trip.
    try:
        json.dumps(result.to_dict())
    except (TypeError, ValueError) as e:
        violations.append(f"non-serializable output: {e}")

    if result.status == STATUS_COMPLETE:
        if not result.summary.strip():
            violations.append("complete result without a summary")
        if not result.tables and not result.warnings:
            violations.append("complete result with no tables and no explanation")

    # Analyst flag is mandatory when unconfirmed matches or exclusions exist.
    raw_text = json.dumps(result.to_dict().get("raw", {}), ensure_ascii=False)
    if '"needs_confirmation": [' in raw_text and \
            '"needs_confirmation": []' not in raw_text and \
            not result.requires_analyst_review:
        violations.append("unconfirmed matches present but analyst flag unset")
        result.requires_analyst_review = True

    if violations:
        logger.warning(f"[ComputationGuard] {result.tool_id}: {violations}")
        if result.status == STATUS_COMPLETE:
            result.status = STATUS_PARTIAL
        result.warnings = list(result.warnings) + [
            f"Output validation: {v}" for v in violations
        ]
        result.requires_analyst_review = True
    # Audit trail: the report itself records what the guard found.
    result.validation["computation_guard"] = {
        "post": "violations" if violations else "passed",
        "violations": list(violations),
    }
    return result
