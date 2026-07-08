"""ToolResult — the single structured contract every programme tool returns.

The LLM never sees engine dataclasses; it sees (and may only narrate) the
JSON-safe ToolResult. Adapters build it, the computation guard validates it,
the narrative composer/guard consume it, and the frontend renders it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

STATUS_COMPLETE = "complete"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"
STATUSES = (STATUS_COMPLETE, STATUS_PARTIAL, STATUS_FAILED)


def json_safe(value: Any) -> Any:
    """Recursively convert engine output (dataclasses, datetimes, Enums, sets)
    into JSON-serializable primitives. Datetimes become ISO-8601 strings."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(v) for v in value]
    return str(value)


@dataclass
class ArtifactBlob:
    """In-memory artifact produced by an adapter; the executor persists it
    to disk and swaps it for a download URL in ToolResult.artifacts."""
    filename: str
    kind: str          # "xlsx"
    data: bytes


@dataclass
class ToolResult:
    tool_id: str
    status: str = STATUS_COMPLETE            # complete | partial | failed
    summary: str = ""                        # deterministic one-liner (NOT LLM)
    tables: List[Dict[str, Any]] = field(default_factory=list)
    # tables: [{"title", "columns": [str], "rows": [[cell,...]], "caption"?}]
    charts: List[Dict[str, Any]] = field(default_factory=list)
    # charts: [{"chart_id", "type": "line", "title", "x_label", "y_label",
    #           "series": [{"name", "points": [{"x": iso, "y": float|None,
    #                                           "marker": str|None}]}]}]
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    # artifacts: [{"artifact_id", "kind", "filename", "url"}]
    warnings: List[str] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)
    requires_analyst_review: bool = False
    raw: Dict[str, Any] = field(default_factory=dict)
    # Validation audit trail — every report carries the record of which guards
    # ran and what they found, so an analyst can see HOW the output was
    # validated, not just the output. Populated by executor/guards/narrative:
    #   {"computation_guard": {"pre": "passed"|"failed",
    #                          "post": "passed"|"violations", "violations": []},
    #    "narrative_guard": {"status": "approved"|"rewritten_then_approved"|
    #                        "fallback_after_rejection"|"llm_unavailable"|
    #                        "deterministic_only", "violations": []}}
    validation: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return json_safe(asdict(self))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


AdapterOutput = Tuple[ToolResult, List[ArtifactBlob]]


def failed_result(tool_id: str, message: str,
                  caveats: Optional[List[str]] = None) -> ToolResult:
    return ToolResult(
        tool_id=tool_id, status=STATUS_FAILED, summary=message,
        warnings=[message], caveats=caveats or [],
        requires_analyst_review=True,
    )
