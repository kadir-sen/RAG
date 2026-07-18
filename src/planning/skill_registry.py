"""Skill registry (Sprint C) — the allow-list of capabilities a plan may use.

The decomposer proposes plans, but it can only reference a skill that exists
here; the validator rejects anything else. This is what keeps an LLM-proposed
plan from inventing a tool. Each skill wraps an *existing* COAir capability
(RAG retrieval, the SQL planner/executor, programme engines, report assembly)
behind a typed input/output contract, so the executor can pass structured
outputs between steps deterministically.

Handlers are resolved at execution time (see plan_executor) — the registry
itself carries no behaviour, only contracts. This keeps the registry importable
without pulling in the router / heavy deps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

RECORD_TYPES = ("programme", "document", "data", "report", "mixed")
COST_LEVELS = ("low", "medium", "high")
RISK_LEVELS = ("normal", "forensic", "legal_sensitive")


@dataclass(frozen=True)
class SkillSpec:
    skill_id: str
    name: str
    record_type: str
    input_contract: List[str]
    output_contract: List[str]
    requires_rerank: bool = False
    requires_schema_catalog: bool = False
    deterministic: bool = True
    cost_level: str = "low"
    risk_level: str = "normal"
    allowed_blocks: List[str] = field(default_factory=list)
    guards: List[str] = field(default_factory=list)
    fallback: Optional[str] = None
    examples: List[str] = field(default_factory=list)


def _s(*a, **k) -> SkillSpec:
    return SkillSpec(*a, **k)


# The registered skills. A curated set that maps to real capabilities — the
# document + data + programme + report families the compound planner needs.
# Everything the decomposer emits must be one of these skill_ids.
SKILLS: Dict[str, SkillSpec] = {
    # ── Document / RAG ──
    "rag.search_evidence": _s(
        "rag.search_evidence", "Search document evidence", "document",
        input_contract=["query"], output_contract=["sources", "answer"],
        requires_rerank=True, deterministic=False, cost_level="medium",
        allowed_blocks=["markdown_text", "caveats"],
        guards=["trust_guard"], examples=["find evidence of the crane breakdown"]),
    "rag.extract_delay_mentions": _s(
        "rag.extract_delay_mentions", "Extract delay events from documents",
        "document", input_contract=["query"],
        output_contract=["candidate_events", "delay_start_date", "sources"],
        requires_rerank=True, deterministic=False, cost_level="medium",
        risk_level="forensic", allowed_blocks=["markdown_text", "caveats"],
        guards=["trust_guard", "claim_language_guard"],
        examples=["is there a delay? when did it start?"]),
    "rag.extract_missing_reporting_mentions": _s(
        "rag.extract_missing_reporting_mentions",
        "Extract missing/incomplete reporting evidence", "document",
        input_contract=["query", "project"],
        output_contract=["missing_reporting", "sources"],
        requires_rerank=True, deterministic=False, cost_level="medium",
        risk_level="forensic", allowed_blocks=["markdown_text", "caveats"],
        guards=["trust_guard", "claim_language_guard"],
        examples=["was reporting incomplete for this project?"]),
    "rag.synthesize_with_citations": _s(
        "rag.synthesize_with_citations", "Cited synthesis", "document",
        input_contract=["query", "sources"],
        output_contract=["markdown", "citations"],
        requires_rerank=True, deterministic=False, cost_level="medium",
        allowed_blocks=["markdown_text", "caveats"], guards=["trust_guard"]),

    # ── Data / Excel (SQL planner + executor from Sprint A) ──
    "data.resolve_tables": _s(
        "data.resolve_tables", "Resolve compatible Excel tables", "data",
        input_contract=["concepts"],
        output_contract=["tables", "schema_mappings", "execution_mode"],
        requires_schema_catalog=True, cost_level="low",
        examples=["find manpower/cost tables"]),
    "data.sql_metric": _s(
        "data.sql_metric", "Run a metric SQL query", "data",
        input_contract=["query", "tables"],
        output_contract=["data_table", "sql", "caveats"],
        requires_schema_catalog=True, cost_level="medium",
        allowed_blocks=["data_table", "caveats", "validation_status"],
        guards=["sql_guard"]),
    "data.compare_metrics": _s(
        "data.compare_metrics", "Compare metrics across projects/periods", "data",
        input_contract=["query", "tables"],
        output_contract=["comparison_table", "caveats"],
        requires_schema_catalog=True, cost_level="medium",
        allowed_blocks=["data_table", "caveats", "validation_status"],
        guards=["sql_guard"], examples=["compare manpower, cost and days"]),
    "data.preview_table": _s(
        "data.preview_table", "Raw table preview", "data",
        input_contract=["tables"], output_contract=["data_table"],
        requires_schema_catalog=True, cost_level="low",
        allowed_blocks=["data_table"]),

    # ── Programme ──
    "programme.inventory": _s(
        "programme.inventory", "Programme / project inventory", "programme",
        input_contract=["query"], output_contract=["inventory", "projects"],
        cost_level="low", allowed_blocks=["data_table", "markdown_text"]),

    # ── Report / output ──
    "report.table_pack": _s(
        "report.table_pack", "Assemble comparison tables + caveats + citations",
        "report", input_contract=["comparison_table"],
        output_contract=["blocks"], cost_level="low",
        allowed_blocks=["data_table", "caveats", "validation_status",
                        "markdown_text"]),
    "report.markdown_answer": _s(
        "report.markdown_answer", "Compose a markdown answer", "report",
        input_contract=["markdown"], output_contract=["blocks"],
        cost_level="low", allowed_blocks=["markdown_text", "caveats"]),
}


def get_skill(skill_id: str) -> Optional[SkillSpec]:
    return SKILLS.get(skill_id)


def all_skill_ids() -> set:
    return set(SKILLS.keys())


def skills_for_record(record_type: str) -> List[SkillSpec]:
    return [s for s in SKILLS.values() if s.record_type == record_type]
