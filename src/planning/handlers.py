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

from .output_planner import plan_output
from .plan_executor import SkillContext, SkillResult
from .schemas import OutputSpec, SubTask

logger = logging.getLogger(__name__)


def _num(v: Any) -> Optional[float]:
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _table_dict_from_result(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize a router DATA result into a {columns, rows} table dict."""
    cols = result.get("result_columns")
    data = result.get("result_data")
    rows = None
    if isinstance(data, dict):
        rows = data.get("rows")
        cols = cols or data.get("columns")
    elif isinstance(data, list):
        rows = data
    if not (cols and rows):
        return None
    norm = [list(r) if isinstance(r, (list, tuple)) else [r] for r in rows]
    norm = [r for r in norm if len(r) == len(cols)]
    if not norm:
        return None
    return {"columns": list(cols), "rows": norm}


def _table_block(table: Dict[str, Any], title: str = "") -> Dict:
    return {"type": "data_table", "title": title,
            "columns": table["columns"], "rows": table["rows"]}


def _resolve_cols(table: Dict[str, Any], output: OutputSpec):
    """Pick x + value column(s) from the OutputSpec, honouring names when they
    exist and degrading to positional (col0=x, col1..=values) otherwise."""
    cols = table.get("columns") or []
    x = output.x if output.x in cols else (cols[0] if cols else None)
    ys = [c for c in (output.series or []) if c in cols]
    if not ys:
        ys = [c for c in cols if c != x][:1]  # first non-x column
    degraded = (output.x and output.x not in cols) or (
        output.series and not [c for c in output.series if c in cols])
    return x, ys, degraded


def _chart_from_table_dict(table: Dict[str, Any], output: OutputSpec
                           ) -> tuple[Optional[Dict], List[str]]:
    """Build a bar/line chart block from a {columns, rows} table, honouring the
    OutputSpec's x/series. Values are copied VERBATIM from the table (no model
    ever produces the numbers), so the chart is faithful by construction.
    Returns (block|None, caveats)."""
    caveats: List[str] = []
    x, ys, degraded = _resolve_cols(table, output)
    cols = table.get("columns") or []
    if not x or not ys or x not in cols:
        return None, ["not enough columns to build the requested chart"]
    if degraded:
        caveats.append(f"chart axes inferred from column order "
                       f"(x={x}, series={', '.join(ys)})")
    xi = cols.index(x)
    title = output.title or ""

    if output.kind == "bar_chart":
        yi = cols.index(ys[0])
        cats, vals = [], []
        for row in table["rows"]:
            v = _num(row[yi])
            if v is None:
                continue
            cats.append(str(row[xi]))
            vals.append(v)
        if not cats:
            return None, ["no numeric rows to chart"]
        return ({"type": "chart", "chart_type": "bar", "title": title,
                 "x_label": x, "y_label": ys[0],
                 "categories": cats, "values": vals}, caveats)

    # line_chart — one series per requested column that carries numbers
    series = []
    for y in ys:
        yi = cols.index(y)
        pts = []
        for row in table["rows"]:
            v = _num(row[yi])
            if v is None:
                continue
            pts.append({"x": str(row[xi]), "y": v})
        if pts:
            series.append({"name": y, "points": pts})
    if not series:
        return None, ["no numeric rows to chart"]
    return ({"type": "chart", "chart_type": "line", "title": title,
             "x_label": x, "y_label": ys[0] if len(ys) == 1 else "value",
             "series": series}, caveats)


def _render_table(table: Optional[Dict[str, Any]], output: Optional[OutputSpec],
                  title: str, query: str = "") -> tuple[List[Dict], List[str]]:
    """Produce the block(s) for a data result, honouring the requested output.

    A chart request → chart block (verbatim values) + the underlying data_table.
    No/other request → just the data_table. When no explicit OutputSpec is set
    (deterministic fallback path), fall back to the English output_planner."""
    if table is None:
        return [], []
    # Derive an OutputSpec from the query if the plan didn't set one.
    if output is None and query:
        op = plan_output(query)
        if op.output_intent == "chart":
            output = OutputSpec(kind=f"{op.chart_type or 'bar'}_chart")
    blocks: List[Dict] = []
    caveats: List[str] = []
    if output and output.kind in ("bar_chart", "line_chart"):
        chart, cav = _chart_from_table_dict(table, output)
        caveats.extend(cav)
        if chart:
            blocks.append(chart)
    blocks.append(_table_block(table, title))
    return blocks, caveats


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

    # ── claim / forensic: the REAL delay chronology engine, as a skill ──
    def h_delay_chronology(st: SubTask, store, ctx: SkillContext) -> SkillResult:
        try:
            from ..delay_reports import run_event_chronology
            r = run_event_chronology(st.inputs.get("query") or ctx.extra.get("query", ""),
                                     router, ctx.doc_ids) or {}
        except Exception as e:
            return SkillResult(
                outputs={"chronology": None},
                caveats=[f"delay chronology unavailable: {e}"])
        ans = r.get("answer", "")
        blocks = list(r.get("blocks") or [])
        if ans and not blocks:
            blocks = [{"type": "markdown_text", "text": ans}]
        return SkillResult(
            outputs={"chronology": ans, "evidence": r.get("sources") or [],
                     "citations": r.get("sources") or []},
            blocks=blocks, sources=r.get("sources") or [],
            caveats=r.get("caveats") or [],
            guards={"trust_guard": "applied", "claim_language_guard": "applied"})

    # ── programme skill ──
    def h_inventory(st: SubTask, store, ctx: SkillContext) -> SkillResult:
        try:
            r = router._handle_programme_query(st.inputs.get("query") or "",
                                               ctx.doc_ids) or {}
        except Exception as e:
            return SkillResult(outputs={"projects": []},
                               caveats=[f"programme inventory unavailable: {e}"])
        tbl = _table_dict_from_result(r)
        return SkillResult(outputs={"inventory": r.get("answer"),
                                    "projects": r.get("projects") or []},
                           blocks=[_table_block(tbl, "Programme inventory")] if tbl else [])

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
        tbl = _table_dict_from_result(r)
        blocks, caveats = _render_table(tbl, st.output, "Result",
                                        ctx.extra.get("query", ""))
        return SkillResult(
            outputs={"data_table": tbl, "sql": r.get("sql"),
                     "answer": r.get("answer")},
            blocks=blocks, caveats=caveats, sources=r.get("sources") or [],
            guards={"sql_guard": "passed" if r.get("sql") else "skipped"})

    def h_compare(st: SubTask, store, ctx: SkillContext) -> SkillResult:
        r = _data(st.inputs.get("query") or "", ctx.doc_ids)
        tbl = _table_dict_from_result(r)
        blocks, caveats = _render_table(tbl, st.output, "Comparison",
                                        ctx.extra.get("query", ""))
        return SkillResult(
            outputs={"comparison_table": tbl},
            blocks=blocks, caveats=caveats + (r.get("caveats") or []),
            guards={"sql_guard": "passed" if r.get("sql") else "skipped"})

    # ── report skills ──
    def h_table_pack(st: SubTask, store, ctx: SkillContext) -> SkillResult:
        # Final assembly. Upstream data steps already emit their table (+ chart if
        # they carried an OutputSpec). This step re-honours the report step's own
        # output directive against the produced table so a chart requested at the
        # report level still appears; and surfaces an unavailable-export note.
        produced = store.get("comparison_table") or store.get("data_table")
        # produced is a {columns, rows} dict from the new data handlers.
        if not isinstance(produced, dict) or "columns" not in produced:
            # nothing renderable was produced upstream
            op0 = plan_output(ctx.extra.get("query", ""))
            cav = ([op0.unavailable_note] if op0.export_format
                   and not op0.export_available and op0.unavailable_note else [])
            if not cav:
                cav = ["No table data was produced to assemble."]
            return SkillResult(caveats=cav)
        blocks: List[Dict] = []
        caveats: List[str] = []
        # Only add a chart here if the report step ITSELF requested one (avoid a
        # duplicate chart when the data step already rendered it).
        if st.output and st.output.kind in ("bar_chart", "line_chart"):
            chart, cav = _chart_from_table_dict(produced, st.output)
            caveats.extend(cav)
            if chart:
                blocks.append(chart)
        op = plan_output(ctx.extra.get("query", ""),
                         is_forensic=ctx.extra.get("forensic", False))
        if op.export_format and not op.export_available and op.unavailable_note:
            caveats.append(op.unavailable_note)
        return SkillResult(outputs={"blocks": "assembled"},
                           blocks=blocks, caveats=caveats)

    def h_markdown(st: SubTask, store, ctx: SkillContext) -> SkillResult:
        md = st.inputs.get("markdown") or store.get("answer") or ""
        return SkillResult(blocks=[{"type": "markdown_text", "text": md}] if md else [])

    return {
        "rag.extract_delay_mentions": h_delay,
        "rag.extract_missing_reporting_mentions": h_missing,
        "rag.search_evidence": h_search,
        "rag.synthesize_with_citations": h_search,
        "claim.delay_chronology": h_delay_chronology,
        "programme.inventory": h_inventory,
        "data.resolve_tables": h_resolve,
        "data.sql_metric": h_sql_metric,
        "data.compare_metrics": h_compare,
        "data.preview_table": h_sql_metric,
        "report.table_pack": h_table_pack,
        "report.markdown_answer": h_markdown,
    }
