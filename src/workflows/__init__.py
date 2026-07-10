"""Registered construction workflows — the workflow-grade skill layer.

A thin façade over the orchestration runners, resolver and programme/delay
handlers: it adds a uniform catalogue (available + planned), a deterministic
planner, an input-resolution summary, caveat aggregation, and structured
"planned/unavailable" responses. The LLM never invents a workflow or tool.
"""

from __future__ import annotations

from .executor import run_workflow, workflow_result_to_response
from .planner import plan
from .registry import WORKFLOWS, get_spec, is_available
from .types import (
    WorkflowContext, WorkflowId, WorkflowPlan, WorkflowResult,
    WorkflowStatus, WorkflowStep,
)

__all__ = [
    "plan", "run_workflow", "workflow_result_to_response",
    "WORKFLOWS", "get_spec", "is_available",
    "WorkflowId", "WorkflowStatus", "WorkflowStep", "WorkflowPlan",
    "WorkflowContext", "WorkflowResult",
]
