"""Skill executor — the ONLY way a programme tool runs.

Whitelist dispatch (registry tool_id → adapter function), computation guard
before and after, artifact persistence under storage/artifacts/<run_id>/.
The LLM can neither name a Python function nor bypass the guards.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

from .adapters import (
    comparison_adapter, critical_path_adapter, dcma_adapter,
    float_erosion_adapter, inventory_adapter, milestone_adapter,
    progress_adapter, resources_adapter, variance_adapter, windows_adapter,
)
from .adapters.xer_loader import XerLoadError
from .guards import computation_guard
from .schemas import AdapterOutput, ArtifactBlob, ToolResult, failed_result

logger = logging.getLogger(__name__)

# Whitelist: tool_id → adapter entry point. Nothing outside this dict runs.
_ADAPTERS: Dict[str, Callable[..., AdapterOutput]] = {
    inventory_adapter.TOOL_ID: inventory_adapter.run,
    dcma_adapter.TOOL_ID: dcma_adapter.run,
    milestone_adapter.TOOL_ID: milestone_adapter.run,
    variance_adapter.TOOL_ID: variance_adapter.run,
    critical_path_adapter.TOOL_ID: critical_path_adapter.run,
    comparison_adapter.TOOL_ID: comparison_adapter.run,
    progress_adapter.TOOL_ID: progress_adapter.run,
    windows_adapter.TOOL_ID: windows_adapter.run,
    float_erosion_adapter.TOOL_ID: float_erosion_adapter.run,
    resources_adapter.TOOL_ID: resources_adapter.run,
}


def known_tool_ids() -> List[str]:
    return sorted(_ADAPTERS)


def run_tool(tool_id: str, records: List[Dict[str, Any]],
             options: Optional[Dict[str, Any]] = None,
             run_id: Optional[str] = None) -> ToolResult:
    """Execute one whitelisted tool with guards. Never raises to the caller."""
    options = options or {}
    adapter = _ADAPTERS.get(tool_id)
    if adapter is None:
        return failed_result(tool_id or "unknown",
                             f"Unknown programme tool '{tool_id}'.")

    problems = computation_guard.validate_inputs(records)
    if problems:
        failed = failed_result(tool_id, " ".join(problems))
        failed.validation["computation_guard"] = {
            "pre": "failed", "violations": list(problems)}
        return failed

    try:
        result, blobs = adapter(records, **options)
    except XerLoadError as e:
        failed = failed_result(tool_id, str(e))
        failed.validation["computation_guard"] = {
            "pre": "failed", "violations": [str(e)]}
        return failed
    except TypeError as e:
        logger.warning(f"[ProgrammeTools] bad options for {tool_id}: {e}")
        return failed_result(tool_id, "Invalid options for this analysis.")
    except Exception as e:
        logger.exception(f"[ProgrammeTools] {tool_id} crashed")
        return failed_result(
            tool_id, f"The analysis engine failed unexpectedly: {e}")

    result = computation_guard.validate_result(result)
    result.validation.setdefault("computation_guard", {})["pre"] = "passed"
    _persist_artifacts(result, blobs, run_id or uuid.uuid4().hex[:12])
    return result


def _persist_artifacts(result: ToolResult, blobs: List[ArtifactBlob],
                       run_id: str) -> None:
    """Write artifact bytes to disk and expose download URLs. Best-effort —
    a disk failure costs the download link, never the analysis."""
    if not blobs:
        return
    try:
        from src.export.artifacts import persist_blobs
        result.artifacts.extend(persist_blobs(blobs, run_id))
    except Exception as e:
        logger.warning(f"[ProgrammeTools] artifact persist failed: {e}")
        result.warnings = list(result.warnings) + [
            "Generated report files could not be saved for download."
        ]
