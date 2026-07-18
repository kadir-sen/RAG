"""Plan validator (Sprint C) — the gate between proposal and execution.

An LLM (or the deterministic decomposer) proposes a plan; nothing runs until it
passes here. Rules:
  * every subtask.skill must resolve in the skill registry (no invented tools);
  * the dependency graph must be a valid DAG (no cycles / dangling refs);
  * inputs a subtask can't obtain (not a plan input, not produced upstream) are
    flagged;
  * any forensic / legal-sensitive skill forces analyst_review_required;
  * guards are unioned from the skills actually used.

Returns a (possibly annotated) plan plus a list of errors. The executor refuses
to run a plan with errors.
"""

from __future__ import annotations

from typing import List, Tuple

from .intent_graph import validate_edges
from .schemas import AdvancedPlan, OUTPUT_KINDS
from .skill_registry import all_skill_ids, get_skill

_FORENSIC = {"forensic", "legal_sensitive"}
# Inputs that are considered ambient (always available from the request/context)
# and therefore never need to be produced by an upstream subtask.
_AMBIENT_INPUTS = {"query", "concepts", "project", "doc_ids", "mode"}


def validate_plan(plan: AdvancedPlan) -> Tuple[AdvancedPlan, List[str]]:
    errors: List[str] = []

    if not plan.subtasks:
        errors.append("plan has no subtasks")
        return plan, errors

    # 1. Every skill must exist in the registry.
    known = all_skill_ids()
    for st in plan.subtasks:
        if st.skill not in known:
            errors.append(f"subtask '{st.id}' uses unknown skill '{st.skill}'")

    # 2. DAG integrity.
    errors.extend(validate_edges(plan.subtasks))

    # 2b. Output directive: kind must be renderable; a chart needs an x column.
    for st in plan.subtasks:
        if st.output is None:
            continue
        if st.output.kind not in OUTPUT_KINDS:
            errors.append(f"subtask '{st.id}' has unknown output kind "
                          f"'{st.output.kind}'")
        if st.output.kind in ("bar_chart", "line_chart") and not st.output.x:
            # not fatal — the executor degrades to positional columns — but flag
            # a chart with no series at all as suspicious
            if not st.output.series:
                errors.append(f"subtask '{st.id}' requests a chart with no x/series")

    # 3. Input availability: each declared input must be ambient or produced by
    #    a (transitive) dependency's output_contract.
    produced_by = {st.id: set(get_skill(st.skill).output_contract)
                   if get_skill(st.skill) else set()
                   for st in plan.subtasks}
    by_id = {st.id: st for st in plan.subtasks}
    for st in plan.subtasks:
        upstream: set = set()
        stack = list(st.depends_on)
        seen = set()
        while stack:
            dep = stack.pop()
            if dep in seen or dep not in by_id:
                continue
            seen.add(dep)
            upstream |= produced_by.get(dep, set())
            stack.extend(by_id[dep].depends_on)
        spec = get_skill(st.skill)
        if not spec:
            continue
        for needed in spec.input_contract:
            if needed in _AMBIENT_INPUTS or needed in st.inputs:
                continue
            if needed not in upstream:
                errors.append(
                    f"subtask '{st.id}' ({st.skill}) needs input '{needed}' "
                    f"which is neither ambient nor produced upstream")

    # 4. Risk → analyst review; union guards from used skills.
    guards = set(plan.guards)
    max_risk = plan.risk_level
    for st in plan.subtasks:
        spec = get_skill(st.skill)
        if not spec:
            continue
        guards.update(spec.guards)
        if spec.risk_level in _FORENSIC:
            plan.analyst_review_required = True
            if spec.risk_level == "legal_sensitive":
                max_risk = "legal_sensitive"
            elif max_risk == "normal":
                max_risk = "forensic"
    plan.guards = sorted(guards)
    plan.risk_level = max_risk

    return plan, errors
