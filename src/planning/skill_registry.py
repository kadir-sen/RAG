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
    when_to_use: str = ""                     # one line to help the LLM planner bind
    supports_chart: bool = False              # can render its table as bar/line chart


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
        allowed_blocks=["data_table", "chart", "caveats", "validation_status"],
        guards=["sql_guard"], supports_chart=True,
        when_to_use="a single metric/aggregate over one data family (manpower, "
                    "equipment, IPC, cost); can render the result as a table or a "
                    "bar/line chart per the output spec",
        examples=["total manpower by month", "equipment utilization by block",
                  "cumulative IPC progress as a line chart"]),
    "data.compare_metrics": _s(
        "data.compare_metrics", "Compare metrics across projects/periods", "data",
        input_contract=["query", "tables"],
        output_contract=["comparison_table", "caveats"],
        requires_schema_catalog=True, cost_level="medium",
        allowed_blocks=["data_table", "chart", "caveats", "validation_status"],
        guards=["sql_guard"], supports_chart=True,
        when_to_use="compare two or more metrics/projects/periods side by side",
        examples=["compare manpower, cost and days across projects"]),
    "data.preview_table": _s(
        "data.preview_table", "Raw table preview", "data",
        input_contract=["tables"], output_contract=["data_table"],
        requires_schema_catalog=True, cost_level="low",
        allowed_blocks=["data_table"],
        when_to_use="show raw rows/columns of a table without aggregation",
        examples=["show the first rows of the manpower sheet"]),

    # ── Programme ──
    "programme.inventory": _s(
        "programme.inventory", "Programme / project inventory", "programme",
        input_contract=["query"], output_contract=["inventory", "projects"],
        cost_level="low", allowed_blocks=["data_table", "markdown_text"],
        when_to_use="list which projects/programmes exist or ran in a period",
        examples=["which projects were active in that period?"]),

    # ── Claim / forensic (wraps the real delay engine) ──
    "claim.delay_chronology": _s(
        "claim.delay_chronology", "Forensic delay chronology (6.1 section)",
        "document", input_contract=["query"],
        output_contract=["chronology", "evidence", "citations", "caveats"],
        requires_rerank=True, deterministic=False, cost_level="high",
        risk_level="forensic",
        allowed_blocks=["markdown_text", "data_table", "html_report_section",
                        "caveats", "validation_status"],
        guards=["trust_guard", "claim_language_guard"],
        when_to_use="produce the real dated, cited forensic delay chronology for a "
                    "named event/area (analyst-reviewed) — use this, not "
                    "rag.extract_delay_mentions, when the user asks to PREPARE a "
                    "delay report/chronology",
        examples=["prepare a delay report for Block A",
                  "delay chronology for the blockwork in 6.1 format"]),

    # ── Report / output ──
    "report.table_pack": _s(
        "report.table_pack", "Assemble comparison tables + caveats + citations",
        "report", input_contract=["comparison_table"],
        output_contract=["blocks"], cost_level="low", supports_chart=True,
        allowed_blocks=["data_table", "chart", "caveats", "validation_status",
                        "markdown_text"],
        when_to_use="final assembly step: fold the upstream table(s) into the "
                    "answer, honouring the requested output format (table/chart)",
        examples=["… and show it as a table", "… as a line chart"]),
    "report.markdown_answer": _s(
        "report.markdown_answer", "Compose a markdown answer", "report",
        input_contract=["markdown"], output_contract=["blocks"],
        cost_level="low", allowed_blocks=["markdown_text", "caveats"],
        when_to_use="final assembly of a prose answer from upstream findings",
        examples=["summarise the findings"]),
}


def catalog_for_prompt() -> str:
    """Render the skill catalog for the LLM planner: id, purpose, contracts,
    when-to-use, examples, output blocks. This is what lets the model bind the
    right skill with the right params instead of guessing."""
    lines: List[str] = []
    for sid, s in SKILLS.items():
        parts = [f"- {sid} — {s.name} (record={s.record_type}"]
        if s.risk_level != "normal":
            parts.append(f", risk={s.risk_level}")
        if s.supports_chart:
            parts.append(", chart-capable")
        parts.append(")")
        lines.append("".join(parts))
        lines.append(f"    in: {s.input_contract} | out: {s.output_contract}")
        if s.when_to_use:
            lines.append(f"    use when: {s.when_to_use}")
        if s.examples:
            lines.append(f"    e.g.: {'; '.join(s.examples[:3])}")
    return "\n".join(lines)


def get_skill(skill_id: str) -> Optional[SkillSpec]:
    return SKILLS.get(skill_id)


def all_skill_ids() -> set:
    return set(SKILLS.keys())


def skills_for_record(record_type: str) -> List[SkillSpec]:
    return [s for s in SKILLS.values() if s.record_type == record_type]
