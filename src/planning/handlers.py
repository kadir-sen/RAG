"""Production skill handlers (Sprint C) — the delegation seam.

Each handler wraps an existing COAir capability behind the skill contract and
returns a SkillResult (structured outputs + content blocks). They are
deliberately thin and defensive: a handler that can't produce its output returns
a caveat, never raises (the executor already isolates failures, but keeping the
router calls guarded means a compound answer degrades gracefully instead of
losing a whole step).

Built lazily against a live router via build_handlers(router); unit tests inject
stubs instead, so this module stays out of the hermetic test path.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .plan_executor import SkillContext, SkillResult
from .schemas import SubTask

logger = logging.getLogger(__name__)


def _table_block_from_result(result: Dict[str, Any], title: str = "") -> List[Dict]:
    """Build a data_table block from a router DATA result, if it carries rows."""
    cols = result.get("result_columns")
    data = result.get("result_data")
    rows = None
    if isinstance(data, dict):
        rows = data.get("rows")
        cols = cols or data.get("columns")
    elif isinstance(data, list):
        rows = data
    if cols and rows:
        norm = [list(r) if isinstance(r, (list, tuple)) else [r] for r in rows]
        norm = [r for r in norm if len(r) == len(cols)]
        if norm:
            return [{"type": "data_table", "title": title,
                     "columns": list(cols), "rows": norm}]
    return []


def _chart_block_from_table(table: Any, chart_type: str) -> Optional[Dict]:
    """Derive a bar/line chart block from tabular data (first col = category,
    second numeric col = value). Values are copied verbatim from the table — no
    LLM invents chart numbers (mirrors the existing chart_guard contract).
    Returns None when the shape isn't chartable."""
    rows = table.get("rows") if isinstance(table, dict) else table
    if not isinstance(rows, list) or len(rows) < 1:
        return None
    cats: List[str] = []
    vals: List[float] = []
    for r in rows:
        if not isinstance(r, (list, tuple)) or len(r) < 2:
            return None
        try:
            vals.append(float(r[1]))
        except (TypeError, ValueError):
            return None
        cats.append(str(r[0]))
    if chart_type == "line":
        return {"type": "chart", "chart_type": "line",
                "series": [{"name": "value",
                            "points": [{"x": c, "y": v}
                                       for c, v in zip(cats, vals)]}]}
    return {"type": "chart", "chart_type": "bar",
            "categories": cats, "values": vals}


def build_handlers(router: Any) -> Dict[str, Any]:
    from ..types import QueryType

    def _doc(query: str, doc_ids):
        return router._handle_document_query(query, doc_ids) or {}

    def _data(query: str, doc_ids):
        return router._handle_data_query(query, doc_ids) or {}

    # ── document skills ──
    def h_delay(st: SubTask, store, ctx: SkillContext) -> SkillResult:
        r = _doc(st.inputs.get("query") or "", ctx.doc_ids)
        ans = r.get("answer", "")
        blocks = [{"type": "markdown_text", "text": ans}] if ans else []
        return SkillResult(
            outputs={"candidate_events": r.get("candidate_events") or [],
                     "delay_start_date": r.get("delay_start_date"),
                     "sources": r.get("sources") or []},
            blocks=blocks, sources=r.get("sources") or [],
            caveats=["Delay screening — analyst review required."],
            guards={"trust_guard": r.get("trust_guard_status", "applied")})

    def h_missing(st: SubTask, store, ctx: SkillContext) -> SkillResult:
        r = _doc(st.inputs.get("query") or "", ctx.doc_ids)
        ans = r.get("answer", "")
        return SkillResult(
            outputs={"missing_reporting": r.get("missing_reporting"),
                     "sources": r.get("sources") or []},
            blocks=[{"type": "markdown_text", "text": ans}] if ans else [],
            sources=r.get("sources") or [],
            caveats=["Reporting-gap screening — not a legal finding."])

    def h_search(st: SubTask, store, ctx: SkillContext) -> SkillResult:
        r = _doc(st.inputs.get("query") or "", ctx.doc_ids)
        ans = r.get("answer", "")
        return SkillResult(outputs={"sources": r.get("sources") or [], "answer": ans},
                           blocks=[{"type": "markdown_text", "text": ans}] if ans else [],
                           sources=r.get("sources") or [])

    # ── programme skill ──
    def h_inventory(st: SubTask, store, ctx: SkillContext) -> SkillResult:
        try:
            r = router._handle_programme_query(st.inputs.get("query") or "",
                                               ctx.doc_ids) or {}
        except Exception as e:
            return SkillResult(outputs={"projects": []},
                               caveats=[f"programme inventory unavailable: {e}"])
        return SkillResult(outputs={"inventory": r.get("answer"),
                                    "projects": r.get("projects") or []},
                           blocks=_table_block_from_result(r, "Programme inventory"))

    # ── data skills ──
    def h_resolve(st: SubTask, store, ctx: SkillContext) -> SkillResult:
        try:
            from ..data_catalog import plan_sql
            from ..document_rag import _current_user_corpus
            concepts = st.inputs.get("concepts") or []
            q = " ".join(concepts) if concepts else (st.inputs.get("query") or "")
            plan = plan_sql(q, corpus_id=_current_user_corpus())
            return SkillResult(outputs={"tables": plan.candidate_table_ids,
                                        "schema_mappings": plan.candidate_columns,
                                        "execution_mode": plan.execution_mode})
        except Exception as e:
            return SkillResult(outputs={"tables": []},
                               caveats=[f"table resolution failed: {e}"])

    def h_sql_metric(st: SubTask, store, ctx: SkillContext) -> SkillResult:
        r = _data(st.inputs.get("query") or "", ctx.doc_ids)
        return SkillResult(
            outputs={"data_table": r.get("result_data"), "sql": r.get("sql"),
                     "answer": r.get("answer")},
            blocks=_table_block_from_result(r, "Result"),
            sources=r.get("sources") or [],
            guards={"sql_guard": "passed" if r.get("sql") else "skipped"})

    def h_compare(st: SubTask, store, ctx: SkillContext) -> SkillResult:
        r = _data(st.inputs.get("query") or "", ctx.doc_ids)
        tbl = _table_block_from_result(r, "Comparison")
        return SkillResult(
            outputs={"comparison_table": r.get("result_data")},
            blocks=tbl,
            caveats=r.get("caveats") or [],
            guards={"sql_guard": "passed" if r.get("sql") else "skipped"})

    # ── report skills ──
    def h_table_pack(st: SubTask, store, ctx: SkillContext) -> SkillResult:
        # The comparison/data table blocks are already emitted upstream; this
        # step marks the answer as report-assembled and honours the output-format
        # intent (chart request → add a chart; unavailable export → graceful note).
        from .output_planner import plan_output
        produced = store.get("comparison_table") or store.get("data_table")
        if produced is None:
            return SkillResult(caveats=["No table data was produced to assemble."])
        op = plan_output(ctx.extra.get("query", ""),
                         is_forensic=ctx.extra.get("forensic", False))
        blocks: List[Dict] = []
        caveats: List[str] = []
        if op.output_intent == "chart":
            chart = _chart_block_from_table(produced, op.chart_type or "bar")
            if chart:
                blocks.append(chart)
        if op.export_format and not op.export_available and op.unavailable_note:
            caveats.append(op.unavailable_note)
        return SkillResult(outputs={"blocks": "assembled",
                                    "output_intent": op.output_intent},
                           blocks=blocks, caveats=caveats)

    def h_markdown(st: SubTask, store, ctx: SkillContext) -> SkillResult:
        md = st.inputs.get("markdown") or store.get("answer") or ""
        return SkillResult(blocks=[{"type": "markdown_text", "text": md}] if md else [])

    return {
        "rag.extract_delay_mentions": h_delay,
        "rag.extract_missing_reporting_mentions": h_missing,
        "rag.search_evidence": h_search,
        "rag.synthesize_with_citations": h_search,
        "programme.inventory": h_inventory,
        "data.resolve_tables": h_resolve,
        "data.sql_metric": h_sql_metric,
        "data.compare_metrics": h_compare,
        "data.preview_table": h_sql_metric,
        "report.table_pack": h_table_pack,
        "report.markdown_answer": h_markdown,
    }
