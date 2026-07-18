"""Advanced-plan data model (Sprint C).

A compound prompt is decomposed into a typed, validated DAG of subtasks. These
dataclasses are the contract between the decomposer (proposes), the validator
(gates), and the executor (runs). Kept dependency-free so they are trivially
testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# plan_type ∈ these; complexity/thinking_budget mirror the budget tiers.
PLAN_TYPES = ("single_skill", "registered_workflow", "compound_analysis",
              "report_generation")
RISK_LEVELS = ("normal", "forensic", "legal_sensitive")


@dataclass
class SubTask:
    id: str
    skill: str                                  # must resolve in the skill registry
    record: str = "mixed"                        # programme|document|data|report|mixed
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: List[str] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)
    requires_rerank: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "skill": self.skill, "record": self.record,
            "inputs": self.inputs, "outputs": self.outputs,
            "depends_on": self.depends_on, "requires_rerank": self.requires_rerank,
        }


@dataclass
class AdvancedPlan:
    plan_type: str = "compound_analysis"
    complexity: str = "medium"                   # low|medium|high
    thinking_budget: str = "medium"              # small|medium|large
    subtasks: List[SubTask] = field(default_factory=list)
    clarifications: List[str] = field(default_factory=list)
    risk_level: str = "normal"
    guards: List[str] = field(default_factory=list)
    analyst_review_required: bool = False
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_type": self.plan_type,
            "complexity": self.complexity,
            "thinking_budget": self.thinking_budget,
            "subtasks": [s.to_dict() for s in self.subtasks],
            "clarifications": self.clarifications,
            "risk_level": self.risk_level,
            "guards": self.guards,
            "analyst_review_required": self.analyst_review_required,
            "reason": self.reason,
        }
