"""Typed workflow model.

A workflow is a registered, construction-domain composition of existing
skills. The LLM never invents workflows or tools: the planner may only choose
a WorkflowId present in the registry, and the executor delegates to whitelist
runners/adapters. Every WorkflowResult is convertible to the existing chat
block contract (backend.models.blocks).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class WorkflowId(str, Enum):
    """The registered construction workflows (available + planned)."""
    PROJECT_DATA_INVENTORY = "project_data_inventory"
    PROGRAMME_INVENTORY = "programme_inventory"
    DCMA_LATEST = "dcma_latest"
    MILESTONE_SHIFT_CHART = "milestone_shift_chart"
    PROGRAMME_VARIANCE = "programme_variance"
    PRELIMINARY_PROGRAMME_PACK = "preliminary_programme_pack"
    DELAY_CHRONOLOGY_SECTION = "delay_chronology_section"
    SQL_METRIC_CHART = "sql_metric_chart"
    CONTEXT_TO_REPORT_SECTION = "context_to_report_section"
    DELAY_BRIEFING = "delay_briefing"
    MONTHLY_PROGRESS_REPORT = "monthly_progress_report"
    PRELIMINARY_DELAY_CLAIM_PACK = "preliminary_delay_claim_pack"
    NOTICE_COMPLIANCE_MATRIX = "notice_compliance_matrix"
    CONTRACT_MECHANISM_SUMMARY = "contract_mechanism_summary"
    METHOD_VIABILITY = "method_viability"
    INTERNAL_EOT_ROADMAP = "internal_eot_roadmap"
    DELAY_EVENT_CANDIDATE_REGISTER = "delay_event_candidate_register"
    EVENT_EVIDENCE_TABLE = "event_evidence_table"


class WorkflowStatus(str, Enum):
    """Catalogue availability state (not the per-run status)."""
    AVAILABLE = "available"
    PARTIAL = "partial"
    PLANNED = "planned"
    UNAVAILABLE = "unavailable"


# Per-run result status (distinct from catalogue WorkflowStatus).
RESULT_SUCCESS = "success"
RESULT_PARTIAL = "partial"
RESULT_CLARIFICATION = "clarification"
RESULT_UNAVAILABLE = "unavailable"
RESULT_FAILED = "failed"


@dataclass
class WorkflowStep:
    """One declared step of a workflow (descriptive; runners enforce)."""
    step_id: str
    tool_id: str
    description: str
    required: bool = True
    requires_llm: bool = False
    human_gate: bool = False
    expected_outputs: List[str] = field(default_factory=list)
    # "skip_with_caveat" | "ask_clarification" | "fail_workflow"
    fallback: str = "skip_with_caveat"


@dataclass
class WorkflowPlan:
    """A resolved intent → workflow mapping, ready to execute."""
    workflow_id: WorkflowId
    user_goal: str
    status: WorkflowStatus
    risk_level: str = "medium"
    required_inputs: List[str] = field(default_factory=list)
    steps: List[WorkflowStep] = field(default_factory=list)
    expected_blocks: List[str] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)
    analyst_review_required: bool = False
    unavailable_reason: str = ""
    # planner-populated runtime params (mode, schema, period, clarification…)
    params: Dict[str, Any] = field(default_factory=dict)
    # provenance of the match: "deterministic" | "memory" | "llm"
    source: str = "deterministic"


@dataclass
class WorkflowContext:
    """Everything the executor + telemetry may read about one run."""
    user_query: str
    conversation_id: str = ""
    project_id: Optional[str] = None
    corpus_id: str = ""
    selected_files: List[str] = field(default_factory=list)
    selected_xers: List[str] = field(default_factory=list)
    selected_excel_tables: List[str] = field(default_factory=list)
    selected_documents: List[str] = field(default_factory=list)
    intermediate_outputs: Dict[str, Any] = field(default_factory=dict)
    caveats: List[str] = field(default_factory=list)
    artifacts: List[dict] = field(default_factory=list)
    validation_status: Dict[str, str] = field(default_factory=dict)
    analyst_review_required: bool = False


@dataclass
class WorkflowResult:
    """Uniform, chat-block-convertible outcome of one workflow run."""
    workflow_id: WorkflowId
    status: str                       # RESULT_* above
    blocks: List[dict] = field(default_factory=list)
    answer: str = ""
    caveats: List[str] = field(default_factory=list)
    artifacts: List[dict] = field(default_factory=list)
    sources: List[dict] = field(default_factory=list)
    primary_artifact: Optional[dict] = None
    trust_guard: Optional[dict] = None
    validation: Dict[str, str] = field(default_factory=dict)
    selected_inputs_summary: str = ""
    analyst_review_required: bool = False
    substitute: Optional[str] = None   # WorkflowId value for planned/unavailable
    debug_trace: Dict[str, Any] = field(default_factory=dict)
