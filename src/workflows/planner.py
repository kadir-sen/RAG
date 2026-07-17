"""Deterministic workflow planner.

Maps a user query to a registered WorkflowId. Deterministic-first: explicit
trigger phrases and the existing composite/programme/delay matchers decide the
route. The LLM may only act as a *validated secondary* classifier (stubbed and
disabled this sprint) and can never invent a workflow id — it may only pick one
already present in the registry.

The planner CLAIMS workflow-grade requests (so they gain the input-resolution
summary + uniform result) and returns None for plain RAG/data questions, which
then flow through the router's normal classification unchanged.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .registry import COMPOSITE_TO_WORKFLOW, WORKFLOWS, WorkflowSpec
from .types import WorkflowId, WorkflowPlan, WorkflowStatus

logger = logging.getLogger(__name__)


# Planned/unavailable trigger table (checked AFTER available matches).
_PLANNED_TRIGGERS = [
    (WorkflowId.NOTICE_COMPLIANCE_MATRIX,
     [r"notice\s+compliance", r"compliance\s+matrix"]),
    (WorkflowId.INTERNAL_EOT_ROADMAP,
     [r"internal\s+eot", r"\beot\b.*roadmap", r"eot\s+claim\s+roadmap"]),
    (WorkflowId.PRELIMINARY_DELAY_CLAIM_PACK,
     [r"delay\s+claim\s+(report\s+)?pack",
      r"(preliminary|prelim)\w*\s+delay\s+claim"]),
    (WorkflowId.CONTRACT_MECHANISM_SUMMARY,
     [r"contract\s+mechanism", r"(eot|extension)\s+mechanism",
      r"notice\s+period", r"contract.*notice\s+period",
      r"what.*notice.*contract"]),
    (WorkflowId.METHOD_VIABILITY,
     [r"method\s+(statement\s+)?viability", r"delay\s+analysis\s+method"]),
    (WorkflowId.DELAY_BRIEFING,
     [r"delay\s+briefing"]),
    (WorkflowId.MONTHLY_PROGRESS_REPORT,
     [r"monthly\s+progress\s+(report|summary|update)",
      r"progress\s+report\s+for\s+(the\s+)?month"]),
]

# Light negative guard for the SQL metric data-gate — keep document/contract
# questions out of the deterministic-table path.
_SQL_GATE_NEG = re.compile(
    r"contract|clause|notice|letter|correspondence|\bwhy\b|explain|entitle|"
    r"liab|claim", re.IGNORECASE)
_SQL_DIM = re.compile(r"\b(by|per)\s+\w+", re.IGNORECASE)


def _plan_from_spec(spec: WorkflowSpec, query: str, source: str = "deterministic",
                    **params) -> WorkflowPlan:
    return WorkflowPlan(
        workflow_id=spec.workflow_id,
        user_goal=query,
        status=spec.status,
        risk_level=spec.risk,
        required_inputs=list(spec.required_inputs),
        steps=list(spec.steps),
        expected_blocks=list(spec.expected_blocks),
        analyst_review_required=spec.analyst_review_required,
        unavailable_reason=("" if spec.status in (WorkflowStatus.AVAILABLE,
                                                  WorkflowStatus.PARTIAL)
                            else f"{spec.name} is planned but not yet built."),
        params=params,
        source=source,
    )


def _llm_validate(candidate: Optional[WorkflowPlan], query: str
                  ) -> Optional[WorkflowPlan]:
    """Secondary LLM classifier hook — DISABLED this sprint.

    When enabled it may only confirm/deny a candidate or pick another
    *registered* WorkflowId; it can never invent one. Pass-through for now.
    """
    return candidate


def plan(query: str) -> Optional[WorkflowPlan]:
    """Return a WorkflowPlan for a workflow-grade query, else None."""
    q = (query or "").lower().strip()
    if not q:
        return None

    # 1) Existing composite match → mapped WorkflowId (inherits tuned gates).
    try:
        from src.orchestration import match_composite
        m = match_composite(q)
    except Exception as e:
        logger.debug(f"[Planner] composite match skipped: {e}")
        m = None
    if m:
        wid = COMPOSITE_TO_WORKFLOW.get(m["id"])
        if wid is None:
            # programme_compare / evidence_explain: keep their composite route.
            return None
        params = {}
        if wid == WorkflowId.DELAY_CHRONOLOGY_SECTION:
            params["mode"] = "html"
        return _plan_from_spec(WORKFLOWS[wid], query, **params)

    # 2/3) Programme registry — inventory (single skill) + preliminary pack.
    try:
        from src.programme_tools import match_query as _pt_match
        pm = _pt_match(q)
    except Exception as e:
        logger.debug(f"[Planner] programme match skipped: {e}")
        pm = None
    if pm:
        if pm.get("kind") == "workflow":
            return _plan_from_spec(WORKFLOWS[WorkflowId.PRELIMINARY_PROGRAMME_PACK],
                                   query)
        if pm.get("id") == "programme.inventory":
            return _plan_from_spec(WORKFLOWS[WorkflowId.PROGRAMME_INVENTORY],
                                   query)
        # Plain dcma / milestone programme-tool queries stay on the legacy
        # PROGRAMME route (reached as workflows via composite triggers only).
        return None

    # 3.4) Event evidence table — from CONFIRMED events. Checked before the
    #      register/chronology so "evidence for Event 01" is not swallowed.
    if re.search(r"evidence\s+table|evidence\s+for\s+(confirmed\s+|the\s+)?"
                 r"(event|delay)|which\s+documents?\s+support|"
                 r"supporting\s+correspondence\s+for", q):
        return _plan_from_spec(
            WORKFLOWS[WorkflowId.EVENT_EVIDENCE_TABLE], query)

    # 3.5) Candidate delay-event register — distinct from a 6.1 chronology:
    #      the analyst-reviewable register of extracted candidate events.
    if re.search(r"candidate\s+delay\s+event|delay\s+event\s+register|"
                 r"register\s+of\s+delay\s+events|suggest\w*\s+delay\s+events",
                 q):
        return _plan_from_spec(
            WORKFLOWS[WorkflowId.DELAY_EVENT_CANDIDATE_REGISTER], query)

    # 4) Delay-report registry → plain 6.1 chronology section.
    try:
        from src.delay_reports import match_query as _dr_match
        dm = _dr_match(q)
    except Exception as e:
        logger.debug(f"[Planner] delay match skipped: {e}")
        dm = None
    if dm:
        return _plan_from_spec(WORKFLOWS[WorkflowId.DELAY_CHRONOLOGY_SECTION],
                               query, mode="plain")

    # 5) Registry-triggered workflows. Available/partial ones dispatch to their
    #    adapter; planned ones return a clean structured "not built yet, here's
    #    the substitute" — never a generic RAG/document error.
    for wid, pats in _PLANNED_TRIGGERS:
        if any(re.search(p, q) for p in pats):
            return _plan_from_spec(WORKFLOWS[wid], query)

    # 6) SQL metric data-gate: a metric-by-dimension ask that escaped the
    #    composite chart triggers. Claim it (so DATA never selects a wrong
    #    table); the executor returns a clarification if no compatible table.
    try:
        from src.orchestration.resolver import detect_schema
        schema = detect_schema(q)
    except Exception:
        schema = None
    if schema and _SQL_DIM.search(q) and not _SQL_GATE_NEG.search(q):
        return _plan_from_spec(WORKFLOWS[WorkflowId.SQL_METRIC_CHART], query)

    # 7) Query-pattern memory — SECONDARY signal only. Consulted after every
    #    deterministic branch; can only point at a registered+available
    #    workflow (validated inside query_patterns). Never invents, never
    #    overrides a deterministic match.
    hint = _memory_suggest(query)
    if hint is not None:
        spec = WORKFLOWS.get(hint["workflow_id"])
        if spec is not None:
            return _plan_from_spec(spec, query, source="memory")

    return None


def _memory_suggest(query: str):
    """Look up the query-pattern memory. Isolated + best-effort so a learning
    failure never affects deterministic routing."""
    try:
        from src.learning import query_patterns
        return query_patterns.suggest(query)
    except Exception as e:
        logger.debug(f"[Planner] memory suggest skipped: {e}")
        return None
