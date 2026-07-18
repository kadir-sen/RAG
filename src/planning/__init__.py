"""Advanced compound-analysis planner (Sprint C).

Wraps — never replaces — the existing single-route path. A simple prompt returns
a single_skill plan and the caller falls through to the fast route; only a
genuinely compound (multi-record / multi-step) prompt is decomposed into a
validated subtask DAG and executed here.

Public surface:
  is_compound(query)                     — cheap trigger check
  decompose(query)                       — build an AdvancedPlan
  validate_plan(plan)                    — gate (rejects invented skills)
  execute_plan(plan, handlers, ctx)      — run the DAG
  SKILLS / get_skill                     — the capability allow-list
"""

from .budget import Budget, budget_for, tier_for_complexity
from .output_planner import (OutputPlan, plan_output, is_export_available)
from .plan_executor import (Handler, SkillContext, SkillResult, execute_plan)
from .plan_validator import validate_plan
from .schemas import AdvancedPlan, SubTask
from .skill_registry import SKILLS, SkillSpec, get_skill, all_skill_ids
from .task_decomposer import decompose, is_compound

__all__ = [
    "is_compound", "decompose", "validate_plan", "execute_plan",
    "AdvancedPlan", "SubTask", "SkillContext", "SkillResult", "Handler",
    "SKILLS", "SkillSpec", "get_skill", "all_skill_ids",
    "Budget", "budget_for", "tier_for_complexity",
    "OutputPlan", "plan_output", "is_export_available",
]
