"""
Shared types used across modules.
Lives here to prevent circular imports between router, planner, executor, etc.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any


# ── Query Types ──────────────────────────────────────────────

class QueryType(Enum):
    DOCUMENT = "document"
    DATA = "data"
    HYBRID = "hybrid"
    TIMELINE = "timeline"


# ── Router Decision ──────────────────────────────────────────

@dataclass
class RouterDecision:
    """Result of query classification."""
    query_type: QueryType
    confidence: float            # 0.0 – 1.0
    reasons: List[str]           # human-readable explanation
    used_llm: bool = False
    llm_usage: Optional[Dict[str, Any]] = None


# ── Plan Step Types ──────────────────────────────────────────

class StepType(Enum):
    SQL = "sql"
    DOCUMENT = "document"
    TIMELINE = "timeline"
    COMBINE = "combine"
    FILTER = "filter"


@dataclass
class PlanStep:
    """A single step in the execution plan."""
    step_id: int
    step_type: str               # StepType value
    description: str
    instruction: str
    depends_on: List[int] = field(default_factory=list)
    result: Optional[Any] = None
    status: str = "pending"      # pending | running | done | error
    error: Optional[str] = None


@dataclass
class QueryPlan:
    """A plan containing ordered steps to answer a query."""
    original_query: str
    steps: List[PlanStep] = field(default_factory=list)
    is_simple: bool = True
    plan_rationale: str = ""


# ── Structured Errors ────────────────────────────────────────

@dataclass
class StepError:
    """Structured error from a plan step."""
    step_id: int
    step_type: str
    error_message: str
    recoverable: bool = False


@dataclass
class PlanExecutionError:
    """Returned when a plan fails instead of producing garbage."""
    failed_step: StepError
    completed_steps: List[int]
    partial_results: Dict[int, Any] = field(default_factory=dict)

    @property
    def user_message(self) -> str:
        return (
            f"Query could not be completed: step {self.failed_step.step_id} "
            f"({self.failed_step.step_type}) failed — {self.failed_step.error_message}"
        )


# ── LLM Usage ────────────────────────────────────────────────

@dataclass
class LLMUsage:
    """Token/cost accounting for a single LLM call."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_estimate: float = 0.0
    model: str = ""
    latency_ms: float = 0.0
    cache_hit: bool = False


@dataclass
class LLMResponse:
    """Unified return from llm_client.generate_text."""
    text: str
    usage: LLMUsage
    raw: Optional[Any] = None
