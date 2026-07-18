"""Task decomposer (Sprint C) — turn a compound prompt into a subtask DAG.

Two paths, deterministic-first:
  * a rule-based decomposer detects record-type + step cues (Turkish and
    English) and emits a wired DAG — free, offline, reproducible, and the one
    the tests pin;
  * an optional LLM path proposes a plan when the deterministic cues are thin.
    The LLM only *proposes*; the plan_validator then rejects any invented skill,
    so an LLM can never widen the tool set.

The decomposer decides *whether* a prompt is compound at all: a simple, single-
record prompt returns a single_skill plan (the caller then falls through to the
existing fast route). It commits to compound_analysis only when the prompt spans
multiple records or explicit multi-step work.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

from .budget import tier_for_complexity
from .schemas import AdvancedPlan, SubTask

logger = logging.getLogger(__name__)


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").lower()).strip()


# Cue vocabularies. English-only — the product (files, inputs, outputs) is always
# English. Substring match on the normalized query.
_DELAY_CUES = ["delay", "delayed", "delay event", "time impact", "slippage"]
_MISSING_REPORT_CUES = ["missing reporting", "missing report", "incomplete report",
                        "reporting gap", "unreported", "reporting shortfall"]
_INVENTORY_CUES = ["another project", "other project", "other projects",
                   "same period", "which projects", "during this period",
                   "in that period", "any other project"]
_DATA_METRIC_CUES = ["manpower", "man power", "labour", "labor", "workforce",
                     "cost", "day", "days", "equipment", "plant", "ipc",
                     "progress", "boq"]
_COMPARE_CUES = ["compare", "comparison", "comparative", "versus", " vs ",
                 "side by side", "against"]
_TABLE_OUT_CUES = ["table", "as a table", "in a table", "tabular", "table form"]
_CHART_OUT_CUES = ["chart", "graph", "plot", "visualize", "visualise"]

# Step separators that hint at explicit multi-step intent.
_STEP_CUES = ["first", "then", "next", "after that", "afterwards",
              "subsequently", "finally", "step "]


def _has(nq: str, cues: List[str]) -> bool:
    return any(c in nq for c in cues)


def _count_steps(nq: str) -> int:
    return sum(nq.count(c) for c in _STEP_CUES)


def is_compound(query: str) -> bool:
    """A prompt is compound when it spans >=2 record types OR chains explicit
    multi-step work over documents+data. Deliberately conservative — a false
    positive here steals a simple prompt from the fast route."""
    nq = _norm(query)
    records = 0
    if _has(nq, _DELAY_CUES) or _has(nq, _MISSING_REPORT_CUES):
        records += 1
    if _has(nq, _DATA_METRIC_CUES):
        records += 1
    if _has(nq, _INVENTORY_CUES):
        records += 1
    multi_step = _count_steps(nq) >= 2
    return records >= 2 or (records >= 1 and multi_step and
                            (_has(nq, _COMPARE_CUES) or _has(nq, _TABLE_OUT_CUES)))


def decompose(query: str, enable_llm: bool = False) -> AdvancedPlan:
    """Return an AdvancedPlan. Deterministic cues first; optional LLM fallback."""
    nq = _norm(query)
    if not is_compound(query):
        return AdvancedPlan(plan_type="single_skill", complexity="low",
                            thinking_budget="small", subtasks=[],
                            reason="not a compound prompt")

    plan = _deterministic_plan(query, nq)
    if plan.subtasks:
        return plan

    if enable_llm:
        llm_plan = _llm_decompose(query)
        # The LLM only proposes — never trust it unvalidated. Accept only a plan
        # that passes the same gate (no invented skills, valid DAG); otherwise
        # fall through to clarification.
        if llm_plan is not None and llm_plan.subtasks:
            from .plan_validator import validate_plan
            _, errs = validate_plan(llm_plan)
            if not errs:
                return llm_plan
            logger.info(f"[decomposer] LLM plan rejected by validator: {errs}")

    # Compound-looking but no concrete cues matched → ask for clarification.
    return AdvancedPlan(plan_type="compound_analysis", complexity="medium",
                        thinking_budget="medium", subtasks=[],
                        clarifications=["Could you specify which records to "
                                        "analyse (documents, programme, or data)?"],
                        reason="compound but under-specified")


def _deterministic_plan(query: str, nq: str) -> AdvancedPlan:
    subtasks: List[SubTask] = []
    forensic = False

    delay_id: Optional[str] = None
    if _has(nq, _DELAY_CUES):
        delay_id = "t_delay"
        subtasks.append(SubTask(
            id=delay_id, skill="rag.extract_delay_mentions", record="document",
            inputs={"query": query},
            outputs=["candidate_events", "delay_start_date", "sources"],
            requires_rerank=True))
        forensic = True

    inv_id: Optional[str] = None
    if _has(nq, _INVENTORY_CUES):
        inv_id = "t_inventory"
        deps = [delay_id] if delay_id else []
        subtasks.append(SubTask(
            id=inv_id, skill="programme.inventory", record="programme",
            inputs={"query": query}, outputs=["inventory", "projects"],
            depends_on=deps))

    if _has(nq, _MISSING_REPORT_CUES):
        deps = [x for x in (delay_id, inv_id) if x]
        subtasks.append(SubTask(
            id="t_missing", skill="rag.extract_missing_reporting_mentions",
            record="document", inputs={"query": query, "project": ""},
            outputs=["missing_reporting", "sources"], depends_on=deps,
            requires_rerank=True))
        forensic = True

    data_id: Optional[str] = None
    if _has(nq, _DATA_METRIC_CUES):
        data_id = "t_tables"
        subtasks.append(SubTask(
            id=data_id, skill="data.resolve_tables", record="data",
            inputs={"concepts": _detected_concepts(nq)},
            outputs=["tables", "schema_mappings", "execution_mode"]))
        # a comparison or a plain metric?
        metric_id = "t_metric"
        if _has(nq, _COMPARE_CUES):
            subtasks.append(SubTask(
                id=metric_id, skill="data.compare_metrics", record="data",
                inputs={"query": query}, outputs=["comparison_table", "caveats"],
                depends_on=[data_id]))
        else:
            subtasks.append(SubTask(
                id=metric_id, skill="data.sql_metric", record="data",
                inputs={"query": query},
                outputs=["data_table", "sql", "caveats"], depends_on=[data_id]))

        # output assembly
        if _has(nq, _TABLE_OUT_CUES) or _has(nq, _COMPARE_CUES):
            src = "comparison_table" if _has(nq, _COMPARE_CUES) else "data_table"
            subtasks.append(SubTask(
                id="t_report", skill="report.table_pack", record="report",
                inputs={src: ""}, outputs=["blocks"], depends_on=[metric_id]))

    if not subtasks:
        return AdvancedPlan(plan_type="single_skill", subtasks=[])

    n = len(subtasks)
    complexity = "high" if n >= 4 else ("medium" if n >= 2 else "low")
    plan_type = ("report_generation"
                 if subtasks[-1].skill.startswith("report.")
                 else "compound_analysis")
    return AdvancedPlan(
        plan_type=plan_type, complexity=complexity,
        thinking_budget=tier_for_complexity(complexity), subtasks=subtasks,
        risk_level="forensic" if forensic else "normal",
        reason=f"deterministic decomposition ({n} subtasks)")


def _detected_concepts(nq: str) -> List[str]:
    concepts = []
    if any(c in nq for c in ["manpower", "man power", "labour", "labor",
                             "workforce"]):
        concepts.append("manpower")
    if any(c in nq for c in ["cost", "boq"]):
        concepts.append("cost")
    if any(c in nq for c in ["day", "days", "date", "duration"]):
        concepts.append("date")
    if any(c in nq for c in ["equipment", "plant"]):
        concepts.append("equipment")
    if any(c in nq for c in ["ipc", "progress"]):
        concepts.append("progress")
    return concepts or ["manpower"]


def _llm_decompose(query: str) -> Optional[AdvancedPlan]:  # pragma: no cover
    """Optional LLM proposer. Constrained to registry skills in the prompt; the
    validator is the real enforcer. Disabled by default; returns None on any
    failure so the caller degrades to clarification."""
    try:
        from .. import llm_client
        from .skill_registry import SKILLS
        catalog = "\n".join(f"- {sid}: {s.name} (record={s.record_type})"
                            for sid, s in SKILLS.items())
        prompt = (
            "Decompose the USER PROMPT into a subtask DAG. Use ONLY these skills "
            "(never invent one):\n" + catalog + "\n\n"
            f"USER PROMPT: {query}\n\n"
            'Return JSON {"subtasks":[{"id","skill","record","inputs",'
            '"outputs","depends_on"}]}.')
        resp = llm_client.generate_json(
            prompt, system="You are a planning decomposer. JSON only.")
        raw = resp.raw if isinstance(resp.raw, dict) else {}
        subs = []
        for s in raw.get("subtasks", []) or []:
            subs.append(SubTask(
                id=str(s.get("id")), skill=str(s.get("skill")),
                record=str(s.get("record", "mixed")),
                inputs=s.get("inputs") or {}, outputs=s.get("outputs") or [],
                depends_on=s.get("depends_on") or []))
        if not subs:
            return None
        n = len(subs)
        complexity = "high" if n >= 4 else "medium"
        return AdvancedPlan(plan_type="compound_analysis", complexity=complexity,
                            thinking_budget=tier_for_complexity(complexity),
                            subtasks=subs, reason="llm decomposition")
    except Exception as e:
        logger.warning(f"[decomposer] LLM path failed: {e}")
        return None
