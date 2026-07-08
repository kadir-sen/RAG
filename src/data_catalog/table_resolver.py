"""SQL planner — decide HOW a DATA query should execute before any SQL is made.

Deterministic (no LLM). Extracts required concepts, classifies intent, finds
compatible tables via the schema catalog, and returns an execution_mode so the
caller can pick: deterministic template, generated SQL, clarification, raw
preview, or no-data. This is what makes DATA routing existence-gated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..schema_profiler import normalize
from .column_mapping import CONCEPT_ALIASES
from .schema_catalog import get_schema_catalog

_PREVIEW_PAT = ["show contents", "preview", "first ", " rows", "list columns",
                "what columns", "show the columns", "as a table", "as table",
                "show me the table", "sample rows", "raw data"]
_FILE_LEVEL_PAT = ["per file", "which file", "each file", "by file",
                   "count per file", "most entries", "most rows", "which sheet"]
_CHART_PAT = ["chart", "graph", "plot", "bar chart", "line chart", "visualise",
              "visualize", "visual"]
_COMPARE_PAT = [" vs ", "versus", "compare", "planned vs", "planned versus"]
_AGG_PAT = ["total", "sum", "count", "how many", "average", "avg", "by ",
            "per ", "breakdown", "distribution", "top ", "maximum", "minimum",
            "utilization", "utilisation", "cumulative", "peak"]


@dataclass
class SQLPlan:
    intent: str = "aggregate"        # preview_table|aggregate|compare|chart|file_level_aggregate|cross_table_analysis
    required_concepts: List[str] = field(default_factory=list)
    candidate_table_ids: List[str] = field(default_factory=list)
    candidate_columns: Dict[str, str] = field(default_factory=dict)  # concept→raw col (best table)
    mapping_confidence: str = "none"  # high|medium|low|none
    execution_mode: str = "no_data"   # deterministic_template|generated_sql|ask_clarification|raw_preview|no_data
    reason: str = ""

    def to_dict(self) -> Dict:
        return {
            "intent": self.intent,
            "required_concepts": self.required_concepts,
            "candidate_table_ids": self.candidate_table_ids,
            "candidate_columns": self.candidate_columns,
            "mapping_confidence": self.mapping_confidence,
            "execution_mode": self.execution_mode,
            "reason": self.reason,
        }


def _extract_concepts(nq: str) -> List[str]:
    """Whole-word / whole-phrase concept detection (no substring bleed like
    'men' ⊂ 'equipment')."""
    tokens = set(nq.split())
    padded = f" {nq} "
    found = []
    for concept, aliases in CONCEPT_ALIASES.items():
        for a in [concept] + aliases:
            na = normalize(a)
            if not na:
                continue
            parts = na.split()
            if len(parts) == 1:
                if len(na) >= 4 and na in tokens:   # whole word, ≥4 chars
                    found.append(concept)
                    break
            else:
                if f" {na} " in padded:              # whole phrase
                    found.append(concept)
                    break
    return found


def _classify_intent(nq: str) -> str:
    if any(p in nq for p in _FILE_LEVEL_PAT):
        return "file_level_aggregate"
    if any(p in nq for p in _PREVIEW_PAT):
        return "preview_table"
    if any(p in nq for p in _CHART_PAT):
        return "chart"
    if any(p in nq for p in _COMPARE_PAT):
        return "compare"
    return "aggregate"


def plan_sql(query: str, corpus_id: Optional[str] = None) -> SQLPlan:
    nq = normalize(query)
    intent = _classify_intent(nq)
    concepts = _extract_concepts(nq)
    plan = SQLPlan(intent=intent, required_concepts=concepts)
    cat = get_schema_catalog()

    # Preview / file-level never need the LLM and never need concept mapping.
    if intent == "preview_table":
        tables = cat.list_tables(corpus_id=corpus_id)
        if not tables:
            plan.execution_mode, plan.reason = "no_data", "no structured tables in project"
        else:
            plan.execution_mode = "raw_preview"
            plan.candidate_table_ids = [t.table_id for t in tables[:5]]
            plan.reason = "preview request → raw table preview"
        return plan
    if intent == "file_level_aggregate":
        tables = cat.list_tables(corpus_id=corpus_id)
        plan.execution_mode = "deterministic_template" if tables else "no_data"
        plan.candidate_table_ids = [t.table_id for t in tables]
        plan.reason = "file-level aggregate → deterministic per-file template"
        return plan

    # Concept-driven paths need a compatible table to exist (the existence gate).
    if not concepts:
        # generic aggregate with no recognized concept → let SQL-gen try on any
        # table, but only if some data exists.
        tables = cat.list_tables(corpus_id=corpus_id)
        plan.execution_mode = "generated_sql" if tables else "no_data"
        plan.reason = ("no recognized concept; generic SQL over available data"
                       if tables else "no structured tables in project")
        return plan

    compatible = cat.get_compatible_tables(concepts, corpus_id=corpus_id,
                                           min_coverage=0.75)
    if not compatible:
        partial = cat.get_compatible_tables(concepts, corpus_id=corpus_id,
                                            min_coverage=0.5)
        if partial:
            best = partial[0]
            plan.candidate_table_ids = [t.table_id for t in partial]
            plan.candidate_columns = best.mapped_concepts()
            missing = [c for c in concepts if not best.has_concept(c)]
            plan.mapping_confidence = "low"
            plan.execution_mode = "ask_clarification"
            plan.reason = (f"partial match; missing concept(s): {', '.join(missing)}")
            return plan
        plan.mapping_confidence = "none"
        plan.execution_mode = "no_data"
        plan.reason = (f"no table in this project covers "
                       f"{', '.join(concepts)}")
        return plan

    best = compatible[0]
    plan.candidate_table_ids = [t.table_id for t in compatible]
    plan.candidate_columns = best.mapped_concepts()
    plan.mapping_confidence = "high" if best.mapping_status == "confident" else "medium"
    # deterministic template when the table is a confident canonical kind
    plan.execution_mode = ("deterministic_template"
                           if best.mapping_status == "confident"
                           else "generated_sql")
    plan.reason = (f"{len(compatible)} compatible table(s); "
                   f"best={best.duckdb_table_name} ({best.mapping_status})")
    return plan
