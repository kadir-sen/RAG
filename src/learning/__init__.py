"""Learning / persistent project-memory layer.

Not fine-tuning: a durable metadata + telemetry substrate that, over time,
steers the planner and resolver toward the right workflow, files and schema —
while never silently selecting the wrong input (low confidence → ask) and never
letting the LLM invent a tool/workflow.

Sprint 1 shipped the write side (workflow telemetry). Sprint 2A adds:
- schema_memory: read/confirm API over the already-persistent profiler/catalog
  (wires the previously-dormant persist_mapping / mark_mapping_confirmed).
- workflow telemetry read-side (recent_runs / signature lookup / summary).
Later sprints add document_memory + query_patterns that read from these.
"""

from __future__ import annotations

from . import document_memory, query_patterns, schema_memory
from .workflow_telemetry import (
    query_signature, recent_runs, record_workflow_run,
    runs_for_query_signature, telemetry_summary,
)

__all__ = [
    "record_workflow_run", "recent_runs", "runs_for_query_signature",
    "telemetry_summary", "query_signature",
    "schema_memory", "document_memory", "query_patterns",
]
