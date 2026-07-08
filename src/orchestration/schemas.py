"""Orchestration data contracts.

Blocks themselves are validated in backend.models.blocks (the response-
contract guard); here we define the plan/step/run shapes the executor uses.
Block payloads are plain dicts in the backend.models.blocks shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RetryPolicy:
    max_retries: int = 0
    # What to do when a step (or its guard) ultimately fails:
    # "table" | "markdown" | "deterministic" | "clarification" | "none"
    fallback: str = "none"


@dataclass
class CapabilitySpec:
    capability_id: str
    description: str
    deterministic: bool
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    # guard names applied to this capability's output (documentation +
    # telemetry labels; enforcement lives in the step runners themselves)
    guards: List[str] = field(default_factory=list)


@dataclass
class PlanStep:
    step_id: str
    capability_id: str
    # slot values for the step (chart type, period, event title, want=...)
    params: Dict[str, Any] = field(default_factory=dict)
    needs: List[str] = field(default_factory=list)
    optional: bool = False   # optional steps may be skipped without failing


@dataclass
class CompositePlan:
    intent_id: str
    steps: List[PlanStep]
    slots: Dict[str, Any] = field(default_factory=dict)
    risk: str = "medium"     # "medium" | "high" — high forces trust guard step


@dataclass
class StepResult:
    step_id: str
    capability_id: str
    status: str              # "ok" | "fallback" | "failed" | "skipped"
    output: Any = None       # capability-specific payload
    blocks: List[dict] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)
    guard_status: str = "skipped"   # passed | failed | fallback | skipped
    fallback_used: str = ""
    attempts: int = 1
    latency_ms: float = 0.0
    reason: str = ""


@dataclass
class CompositeResult:
    intent_id: str
    status: str              # "success" | "partial" | "failed" | "needs_clarification"
    blocks: List[dict] = field(default_factory=list)
    answer: str = ""         # short lead-in text for assistant_text
    sources: List[dict] = field(default_factory=list)
    primary_artifact: Optional[dict] = None  # ToolResult dict for context reuse
    trust_guard: Optional[dict] = None
    steps: List[StepResult] = field(default_factory=list)
