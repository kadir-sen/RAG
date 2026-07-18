"""Task decomposer — turn a compound prompt into a validated subtask DAG.

LLM-first (Smart Planner v2): when enabled, an LLM proposes the DAG (which skills,
in what order, and the output format) from the full skill catalog; the
plan_validator gates it (invented skills / bad DAG rejected) with one repair
retry. A deterministic cue-based decomposer remains as the resilience fallback
(LLM unavailable / quota outage) and as the offline default for tests.

The LLM only proposes STRUCTURE — numbers are produced downstream by deterministic
code (SQL + chart_guard + the forensic engine), so an LLM can neither widen the
tool set nor fabricate values. English-only (the product is English-only).
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

from .budget import tier_for_complexity
from .schemas import AdvancedPlan, OutputSpec, SubTask

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


_CONJUNCTIONS = [" and ", " also ", " plus ", " as well as ", " then ",
                 "; ", " additionally "]


def is_multi_ask(query: str) -> bool:
    """Cheap, LLM-free trigger for the router: should this prompt be tried by the
    compound planner BEFORE the single-route fast path?

    True when the prompt is compound, OR when it pairs a forensic/programme ask
    (delay, missing reporting) with an explicit data/chart/table request joined by
    a conjunction — the exact 'delay report for X AND compare Y as a table' shape
    that the fixed delay route would otherwise swallow whole. A single-ask prompt
    (even 'manpower by trade as a table') stays False → fast route."""
    if is_compound(query):
        return True
    nq = _norm(query)
    forensic = _has(nq, _DELAY_CUES) or _has(nq, _MISSING_REPORT_CUES)
    prog = _has(nq, _INVENTORY_CUES)
    data_or_fmt = (_has(nq, _DATA_METRIC_CUES) or _has(nq, _CHART_OUT_CUES)
                   or _has(nq, _TABLE_OUT_CUES))
    conj = _has(nq, _CONJUNCTIONS)
    return (forensic or prog) and data_or_fmt and conj


def decompose(query: str, enable_llm: bool = False) -> AdvancedPlan:
    """Return an AdvancedPlan for a compound prompt.

    LLM-first when enable_llm: an LLM proposes the subtask DAG (structure + output
    format), the validator gates it (rejects invented skills / bad DAG), and one
    repair retry is attempted on validation errors. The deterministic cue plan is
    the resilience fallback (LLM unavailable / quota outage / repair failed), NOT
    the primary. enable_llm defaults False so offline callers/tests get the
    deterministic path unchanged; the router passes ENABLE_LLM_DECOMPOSER."""
    nq = _norm(query)
    if not is_multi_ask(query):
        return AdvancedPlan(plan_type="single_skill", complexity="low",
                            thinking_budget="small", subtasks=[],
                            reason="not a compound prompt")

    if enable_llm:
        from .plan_validator import validate_plan
        llm_plan = _llm_decompose(query)
        if llm_plan is not None and llm_plan.subtasks:
            plan, errs = validate_plan(llm_plan)
            if not errs:
                return plan
            logger.info(f"[decomposer] LLM plan invalid, repairing: {errs}")
            repaired = _llm_decompose(query, repair_errors=errs, prior=llm_plan)
            if repaired is not None and repaired.subtasks:
                plan2, errs2 = validate_plan(repaired)
                if not errs2:
                    return plan2
                logger.info(f"[decomposer] repair still invalid: {errs2}")

    # Deterministic fallback (also the primary when enable_llm is False).
    plan = _deterministic_plan(query, nq)
    if plan.subtasks:
        return plan

    # Compound-looking but nothing concrete → clarify rather than guess.
    return AdvancedPlan(plan_type="compound_analysis", complexity="medium",
                        thinking_budget="medium", subtasks=[],
                        clarifications=["Could you specify which records to "
                                        "analyse (documents, programme, or data) "
                                        "and the output format (table or chart)?"],
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


# Few-shot: the one shape that used to break (a forensic ask + a formatted data
# comparison) — shows the real delay skill + a chart output directive.
_FEWSHOT = '''EXAMPLE
USER PROMPT: prepare a delay report for Block A and compare cost and progress as a line chart
PLAN:
{"subtasks":[
  {"id":"t1","skill":"claim.delay_chronology","record":"document","inputs":{"query":"delay report for Block A"},"outputs":["chronology","evidence","citations"],"depends_on":[]},
  {"id":"t2","skill":"data.resolve_tables","record":"data","inputs":{"concepts":["cost","progress","date"]},"outputs":["tables"],"depends_on":[]},
  {"id":"t3","skill":"data.compare_metrics","record":"data","inputs":{"query":"compare cost and progress over time"},"outputs":["comparison_table"],"depends_on":["t2"],"output":{"kind":"line_chart","x":"date","series":["cost","progress"]}},
  {"id":"t4","skill":"report.table_pack","record":"report","inputs":{"comparison_table":""},"outputs":["blocks"],"depends_on":["t3"],"output":{"kind":"line_chart","x":"date","series":["cost","progress"]}}
]}'''


def _llm_decompose(query: str, repair_errors: Optional[List[str]] = None,
                   prior: Optional[AdvancedPlan] = None
                   ) -> Optional[AdvancedPlan]:  # pragma: no cover
    """LLM proposer. Given the full skill catalog (contracts + when-to-use +
    examples) and the output-format vocabulary, propose a subtask DAG. The
    validator is the real enforcer — this only proposes. Uses the cheap lite model
    with a cache key. Returns None on any failure (caller falls back)."""
    try:
        from .. import llm_client
        from ..config import GEMINI_MODEL_LITE, ENABLE_LITE_TIER
        from .skill_registry import catalog_for_prompt

        repair_block = ""
        if repair_errors and prior is not None:
            import json
            repair_block = (
                "\nYour previous plan was REJECTED for these reasons — fix them "
                "(use only listed skills, valid dependencies, obtainable inputs):\n"
                + "\n".join(f"- {e}" for e in repair_errors)
                + "\nPrevious plan:\n"
                + json.dumps({"subtasks": [s.to_dict() for s in prior.subtasks]})
                + "\n")

        prompt = (
            "Decompose the USER PROMPT into a subtask DAG over the SKILLS below. "
            "Rules:\n"
            "- Use ONLY these skill ids (never invent one).\n"
            "- Each subtask: id, skill, record, inputs, outputs, depends_on, and "
            "optionally output.\n"
            "- 'output' binds the render format to the user's request: "
            '{"kind":"data_table|bar_chart|line_chart|html_report_section|pdf|docx",'
            '"x":"<x column>","series":["<value column>"...]}. Set it on the '
            "step(s) that produce the shown result (the data/report steps).\n"
            "- To PREPARE a delay report/chronology use claim.delay_chronology "
            "(the real forensic engine), not rag.extract_delay_mentions.\n"
            "- Only reference an input that is ambient (query/concepts/project) or "
            "produced by a dependency's outputs.\n\n"
            "SKILLS:\n" + catalog_for_prompt() + "\n\n"
            + _FEWSHOT + "\n\n"
            + repair_block
            + f"USER PROMPT: {query}\n\n"
            'Return ONLY JSON: {"subtasks":[...]}.')

        resp = llm_client.generate_json(
            prompt, system="You are a precise planning decomposer. JSON only.",
            model=GEMINI_MODEL_LITE if ENABLE_LITE_TIER else "",
            cache_key="decompose:" + _norm(query)[:120])
        raw = resp.raw if isinstance(resp.raw, dict) else {}
        subs = []
        for s in raw.get("subtasks", []) or []:
            if not isinstance(s, dict) or not s.get("skill"):
                continue
            subs.append(SubTask(
                id=str(s.get("id") or f"t{len(subs) + 1}"),
                skill=str(s.get("skill")),
                record=str(s.get("record", "mixed")),
                inputs=s.get("inputs") or {}, outputs=s.get("outputs") or [],
                depends_on=s.get("depends_on") or [],
                output=OutputSpec.from_any(s.get("output"))))
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
