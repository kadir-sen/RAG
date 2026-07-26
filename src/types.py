"""
Shared types and validation schemas used across modules.
Lives here to prevent circular imports between router, planner, executor, etc.

Includes:
- Core types (QueryType, RouterDecision, PlanStep, LLMUsage, etc.)
- Pydantic schemas for LLM output validation (SQLGenerationResult, etc.)
"""
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any

from pydantic import BaseModel, field_validator


# ── Query Types ──────────────────────────────────────────────

class QueryType(Enum):
    DOCUMENT = "document"
    DATA = "data"
    HYBRID = "hybrid"
    TIMELINE = "timeline"
    THREAD = "thread"      # correspondence thread view
    DRAFT = "draft"        # draft response generation
    FILE_LIST = "file_list"  # database file listing


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
    provider: str = ""  # "openai" | "claude" | "gemini"


@dataclass
class LLMResponse:
    """Unified return from llm_client.generate_text."""
    text: str
    usage: LLMUsage
    raw: Optional[Any] = None


@dataclass
class DualLLMResponse:
    """Paired responses from LLM providers."""
    gemini: Optional[LLMResponse] = None
    openai: Optional[LLMResponse] = None
    claude: Optional[LLMResponse] = None
    gemini_error: Optional[str] = None
    openai_error: Optional[str] = None
    claude_error: Optional[str] = None


# ── Pydantic Validation Schemas ─────────────────────────────

class SQLGenerationResult(BaseModel):
    """Schema for LLM-generated SQL output."""
    sql: str
    tables: List[str]
    columns: List[str]
    confidence: float  # 0.0 – 1.0
    notes: str = ""

    @field_validator("sql")
    @classmethod
    def sql_must_be_select(cls, v: str) -> str:
        cleaned = v.strip().rstrip(";").strip()
        if not cleaned.upper().startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed")
        dangerous = [
            r'\bDROP\b', r'\bDELETE\b', r'\bINSERT\b', r'\bUPDATE\b',
            r'\bCREATE\b', r'\bALTER\b', r'\bTRUNCATE\b', r'\bGRANT\b',
            r'\bREVOKE\b', r'\bEXEC\b', r'\bEXECUTE\b', r'\bCALL\b',
            r'\bATTACH\b', r'\bDETACH\b', r'\bCOPY\b', r'\bEXPORT\b',
        ]
        for pattern in dangerous:
            if re.search(pattern, cleaned, re.IGNORECASE):
                raise ValueError(f"Dangerous SQL pattern detected: {pattern}")
        if ";" in cleaned:
            raise ValueError("Multiple SQL statements not allowed")
        return cleaned

    @field_validator("confidence")
    @classmethod
    def confidence_range(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    def validate_tables(self, allowed_tables: List[str]) -> bool:
        """Check that referenced tables exist."""
        allowed_lower = {t.lower() for t in allowed_tables}
        for t in self.tables:
            if t.lower() not in allowed_lower:
                return False
        return True


class PlanStepSchema(BaseModel):
    """Schema for a single plan step from LLM."""
    type: str  # sql | document | timeline | combine
    description: str
    instruction: str
    depends_on: List[int] = []

    @field_validator("type")
    @classmethod
    def valid_type(cls, v: str) -> str:
        allowed = {"sql", "document", "timeline", "combine", "filter"}
        if v.lower() not in allowed:
            raise ValueError(f"Invalid step type: {v}. Must be one of {allowed}")
        return v.lower()


class QueryPlanSchema(BaseModel):
    """Schema for LLM-generated query plan."""
    is_simple: bool
    rationale: str = ""
    steps: List[PlanStepSchema]


class ClassificationResult(BaseModel):
    """Schema for LLM query classification (used only as fallback)."""
    query_type: str
    confidence: float = 0.8
    reason: str = ""

    @field_validator("query_type")
    @classmethod
    def valid_query_type(cls, v: str) -> str:
        allowed = {"DOCUMENT", "DATA", "TIMELINE", "HYBRID"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"Invalid query type: {v}")
        return upper


class RelevanceResult(BaseModel):
    """Schema for LLM-generated document relevance classification."""
    relevance: str  # "relevant" | "not_relevant" | "borderline"
    confidence: float = 0.5
    rationale: str = ""
    issue_tags: List[str] = []

    @field_validator("relevance")
    @classmethod
    def valid_relevance(cls, v: str) -> str:
        allowed = {"relevant", "not_relevant", "borderline"}
        lower = v.lower().strip()
        if lower not in allowed:
            raise ValueError(f"Invalid relevance: {v}. Must be one of {allowed}")
        return lower

    @field_validator("confidence")
    @classmethod
    def confidence_range(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class CitationCheckResult(BaseModel):
    """Schema for LLM-based citation support verification."""
    supported: bool
    explanation: str = ""
