"""Plan executor (Sprint C) — run a validated subtask DAG.

Topologically orders the plan, runs each skill's handler in dependency order,
and threads structured outputs through a shared store so a later subtask reads
an earlier one's results deterministically (no re-derivation, no LLM guessing
between steps). Collects blocks / caveats / citations, unions guard statuses,
and surfaces analyst-review when any forensic skill ran.

Handlers are injected (skill_id → callable), which is the delegation seam: in
production they call the router's real capabilities; in tests they are stubs.
The executor never invents behaviour — a plan with no handler for a skill is a
caveat, not a crash.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .intent_graph import PlanGraphError, topo_order
from .plan_validator import validate_plan
from .schemas import AdvancedPlan, SubTask

logger = logging.getLogger(__name__)


@dataclass
class SkillResult:
    outputs: Dict[str, Any] = field(default_factory=dict)
    blocks: List[Dict[str, Any]] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)
    sources: List[Dict[str, Any]] = field(default_factory=list)
    guards: Dict[str, str] = field(default_factory=dict)


@dataclass
class SkillContext:
    router: Any = None
    doc_ids: Optional[List[str]] = None
    budget: Any = None
    extra: Dict[str, Any] = field(default_factory=dict)


Handler = Callable[[SubTask, Dict[str, Any], SkillContext], SkillResult]


def execute_plan(plan: AdvancedPlan, handlers: Dict[str, Handler],
                 ctx: Optional[SkillContext] = None) -> Dict[str, Any]:
    """Execute a plan. Returns a router-shaped result dict with blocks."""
    ctx = ctx or SkillContext()
    plan, errors = validate_plan(plan)
    if errors:
        logger.warning(f"[plan_executor] refused invalid plan: {errors}")
        return {"query_type": "workflow", "answer": "",
                "plan_refused": True, "errors": errors, "blocks": []}

    try:
        order = topo_order(plan.subtasks)
    except PlanGraphError as e:
        return {"query_type": "workflow", "answer": "",
                "plan_refused": True, "errors": [str(e)], "blocks": []}

    store: Dict[str, Any] = {}
    blocks: List[Dict[str, Any]] = []
    caveats: List[str] = []
    sources: List[Dict[str, Any]] = []
    guards: Dict[str, str] = {}
    ran: List[str] = []

    for st in order:
        h = handlers.get(st.skill)
        if h is None:
            caveats.append(f"skill '{st.skill}' has no handler; step skipped")
            continue
        try:
            res = h(st, store, ctx)
        except Exception as e:  # a bad step drops its outputs, never crashes the plan
            logger.warning(f"[plan_executor] subtask '{st.id}' ({st.skill}) failed: {e}")
            caveats.append(f"step {st.id} ({st.skill}) failed: {e}")
            continue
        ran.append(st.id)
        for k, v in (res.outputs or {}).items():
            store[k] = v
        store[f"{st.id}.result"] = res.outputs
        blocks.extend(res.blocks or [])
        caveats.extend(res.caveats or [])
        sources.extend(res.sources or [])
        guards.update(res.guards or {})

    # Validation-status block folds guards + analyst-review.
    if guards or plan.analyst_review_required:
        blocks.append({
            "type": "validation_status",
            "guards": guards,
            "requires_analyst_review": plan.analyst_review_required,
            "fallbacks_used": [],
        })
    if caveats:
        blocks.append({"type": "caveats", "caveats": caveats, "warnings": []})

    answer = _summarize(plan, ran)
    return {
        "query_type": "workflow",
        "answer": answer,
        "blocks": blocks,
        "sources": sources,
        "plan": plan.to_dict(),
        "plan_type": plan.plan_type,
        "requires_analyst_review": plan.analyst_review_required,
        "subtasks_ran": ran,
    }


def _summarize(plan: AdvancedPlan, ran: List[str]) -> str:
    if not ran:
        return ("I planned this as a multi-step analysis but couldn't complete "
                "any step. Please refine the request.")
    return (f"Completed a {plan.plan_type.replace('_', ' ')} over "
            f"{len(ran)} step(s).")
