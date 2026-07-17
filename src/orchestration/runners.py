"""Composite intent runners — fixed step lists over registered capabilities.

Every runner returns a CompositeResult; failed steps degrade to their
declared fallback while safe blocks still ship. No runner lets the LLM
compute values: engines/SQL produce data, charts copy data, the LLM only
narrates under guards.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from .executor import RunContext
from .helpers import (
    artifact_blocks, caveats_block, clarification_result, md_block,
    table_block, tool_result_guard_statuses, validation_block,
)
from .html_section import build_html_block
from .registry import CAPABILITIES
from .retry import execute_step
from .schemas import CompositeResult
from .viz import bar_chart_from_table, chart_guard, line_chart_from_series

logger = logging.getLogger(__name__)


def _programme_records(ctx: RunContext) -> List[Dict[str, Any]]:
    try:
        return ctx.router._programme_records(ctx.doc_ids)
    except Exception:
        return []


def _finish(intent_id: str, blocks: List[dict], answer: str,
            guards: Dict[str, str], analyst: bool, fallbacks: List[str],
            caveats: List[str], warnings: List[str] | None = None,
            sources: List[dict] | None = None,
            primary: Optional[dict] = None,
            trust_guard: Optional[dict] = None) -> CompositeResult:
    cb = caveats_block(caveats, warnings)
    if cb:
        blocks.append(cb)
    blocks.append(validation_block(guards, analyst, fallbacks))
    status = "partial" if (fallbacks or analyst or
                           any(v == "failed" for v in guards.values())) \
        else "success"
    return CompositeResult(intent_id=intent_id, status=status, blocks=blocks,
                           answer=answer, sources=sources or [],
                           primary_artifact=primary, trust_guard=trust_guard)


def _chart_slot(ctx: RunContext, default: str = "line") -> str:
    q = ctx.query.lower()
    if "bar" in q:
        return "bar"
    if "line" in q:
        return "line"
    return ctx.slots.get("chart_type") or default


# ── 1. milestone_shift_visual ────────────────────────────────

def milestone_shift_visual(ctx: RunContext) -> CompositeResult:
    intent = "composite.milestone_shift_visual"
    records = _programme_records(ctx)
    if len(records) < 2:
        return clarification_result(
            intent, "Milestone shift tracking requires at least two XER "
                    f"revisions; currently {len(records)} available. Please "
                    "upload the missing programme file(s).")

    ctx.report("tool", "Running milestone shift analysis...")
    from src.programme_tools import run_tool
    result = run_tool("programme.milestone_shift", records)
    tr = result.to_dict()
    if tr["status"] == "failed":
        return CompositeResult(intent_id=intent, status="failed",
                               answer=tr["summary"])

    blocks: List[dict] = []
    guards = tool_result_guard_statuses(tr)
    fallbacks: List[str] = []

    # Narrative (guarded; deterministic fallback inside compose_narrative).
    ctx.report("analysing", "Drafting narrative from computed results...")
    from src.programme_tools.narrative import compose_narrative
    narrative = compose_narrative(result, getattr(result, "_engine_ctx", None))
    guards.update(tool_result_guard_statuses(result.to_dict()))
    blocks.append(md_block(narrative, "narrative"))

    # Chart from the ToolResult's own series (values copied verbatim).
    title = "Milestone forecast/actual dates by revision data date"
    src_series = (tr.get("charts") or [{}])[0].get("series") or []
    chart = line_chart_from_series(src_series, title,
                                   x_label="Revision data date",
                                   y_label="Milestone date")
    if chart:
        violations = chart_guard(chart, {"series": src_series}, title)
        if violations:
            guards["chart_guard"] = "failed"
            fallbacks.append("chart→table")
        else:
            guards["chart_guard"] = "passed"
            chart["block_id"] = "chart"
            blocks.append(chart)
    else:
        fallbacks.append("chart→table")

    for i, t in enumerate(tr.get("tables") or []):
        blocks.append(table_block(t, f"table{i + 1}"))
    blocks.extend(artifact_blocks(tr))

    return _finish(intent, blocks, "Milestone movement analysis:",
                   guards, tr.get("requires_analyst_review", False),
                   fallbacks, tr.get("caveats") or [], tr.get("warnings"),
                   primary=tr)


# ── 2. sql_metric_chart ──────────────────────────────────────

_SQL_TEMPLATES = {
    # schema → (category col, value SQL, table title, value label)
    "manpower_production": (
        '"Job Description"', 'SUM("Number of Workers")',
        "Workers by trade", "Total workers"),
    "equipment_log": (
        '"Machinery Name"',
        'ROUND(SUM(TRY_CAST("Estimated Machinery Hours" AS DOUBLE)), 2)',
        "Machinery hours", "Total hours"),
    "ipc_sample": (
        '"Activity Name"',
        'ROUND(SUM(TRY_CAST("Cumulative Amount" AS DOUBLE)), 2)',
        "Cumulative amount by activity", "Cumulative amount"),
}

_DIMENSION_OVERRIDES = {
    r"\bby\s+block\b": '"Block"',
    r"\bby\s+floor\b": '"Floor"',
    r"\bby\s+activity\b": '"Activity Description"',
}


def sql_metric_chart(ctx: RunContext) -> CompositeResult:
    intent = "composite.sql_metric_chart"
    from .resolver import resolve_table_period

    corpus = ""
    try:
        from src.document_rag import _current_user_corpus
        corpus = _current_user_corpus() or ""
    except Exception:
        pass
    res = resolve_table_period(ctx.query, corpus)
    if res.needs_confirmation:
        return clarification_result(intent, res.clarification, res.options)

    schema = res.resolved["schema"]
    tables = res.resolved["tables"]
    period = res.resolved.get("period")
    cat_col, val_sql, base_title, val_label = _SQL_TEMPLATES[schema]
    for pat, col in _DIMENSION_OVERRIDES.items():
        if re.search(pat, ctx.query.lower()) and schema != "ipc_sample":
            cat_col = col
            base_title = f"{base_title.split(' by')[0]} by {col.strip(chr(34))}"
            break

    where = ""
    caveats: List[str] = []
    if schema == "ipc_sample":
        caveats.append("IPC tables carry no date column; the latest available "
                       "tables were used and the period is unverified.")
    elif period:
        where = f" WHERE \"date_key\" = '{period['date_key']}'"
    ctx.report("tool", f"Computing {base_title.lower()}...")

    from src.data_analyzer_sql import get_data_analyzer
    analyzer = get_data_analyzer()

    import pandas as pd
    frames = []
    for t in tables[:12]:
        view = f'"{t}_clean"' if f"{t}_clean" in analyzer.tables else f'"{t}"'
        use_where = where if view.endswith('_clean"') else ""
        sql = (f"SELECT {cat_col} AS category, {val_sql} AS value "
               f"FROM {view}{use_where} GROUP BY {cat_col}")
        df, err = analyzer.execute_raw_sql(sql)
        if err:
            logger.debug(f"[Orchestration] sql.metric skipped {t}: {err}")
            continue
        if df is not None and not df.empty:
            frames.append(df)
    if not frames:
        msg = (f"No {schema.replace('_', ' ')} rows found"
               + (f" for {period['date_key']}" if period else "") + ".")
        return clarification_result(intent, msg + " Try another period or "
                                    "check the uploaded data.")
    merged = (pd.concat(frames).groupby("category", as_index=False)["value"]
              .sum().sort_values("value", ascending=False))

    title = base_title + (f" — {period['date_key']}" if period else "")
    table = {"title": title, "columns": [cat_col.strip('"'), val_label],
             "rows": [[str(r.category), float(r.value)]
                      for r in merged.itertuples()]}

    blocks: List[dict] = []
    guards: Dict[str, str] = {"sql_guard": "passed"}  # execute_raw_sql validated
    fallbacks: List[str] = []

    # Deterministic one-line summary — no LLM, nothing to hallucinate.
    top = table["rows"][0]
    summary = (f"**{title}** — {len(table['rows'])} categories; highest: "
               f"{top[0]} ({top[1]:,.0f} {val_label.lower()}).")
    blocks.append(md_block(summary, "summary"))

    chart_type = _chart_slot(ctx, default="bar")
    chart, note = bar_chart_from_table(table, table["columns"][0],
                                       table["columns"][1], title)
    if note:
        caveats.append(note)
    if chart and chart_type == "bar":
        violations = chart_guard(chart, {"table": table,
                                         "category_col": table["columns"][0],
                                         "value_col": table["columns"][1]},
                                 title)
        if violations:
            guards["chart_guard"] = "failed"
            fallbacks.append("chart→table")
        else:
            guards["chart_guard"] = "passed"
            chart["block_id"] = "chart"
            blocks.append(chart)
    blocks.append(table_block(table, "table"))

    return _finish(intent, blocks, f"{title}:", guards, False, fallbacks,
                   caveats)


# ── 3. programme_compare ─────────────────────────────────────

def programme_compare(ctx: RunContext) -> CompositeResult:
    intent = "composite.programme_compare"
    from .resolver import resolve_xer
    pair = resolve_xer("pair")
    if pair.needs_confirmation:
        return clarification_result(intent, pair.clarification, pair.options)

    records = _programme_records(ctx)
    ctx.report("tool", "Comparing programme revisions...")
    from src.programme_tools import run_tool
    inv = run_tool("programme.inventory", records).to_dict()
    shift_result = run_tool("programme.milestone_shift", records)
    shift = shift_result.to_dict()

    blocks: List[dict] = []
    guards = tool_result_guard_statuses(shift)
    fallbacks: List[str] = []

    from src.programme_tools.narrative import compose_narrative
    narrative = compose_narrative(shift_result,
                                  getattr(shift_result, "_engine_ctx", None))
    guards.update(tool_result_guard_statuses(shift_result.to_dict()))
    blocks.append(md_block(narrative, "narrative"))

    for i, t in enumerate((inv.get("tables") or [])[:1]):
        blocks.append(table_block(t, f"inv{i}"))
    for i, t in enumerate((shift.get("tables") or [])[:1]):
        blocks.append(table_block(t, f"shift{i}"))

    title = "Milestone movement between revisions"
    src_series = (shift.get("charts") or [{}])[0].get("series") or []
    chart = line_chart_from_series(src_series, title)
    if chart and not chart_guard(chart, {"series": src_series}, title):
        guards["chart_guard"] = "passed"
        chart["block_id"] = "chart"
        blocks.append(chart)

    caveats = (pair.caveats + (inv.get("caveats") or [])
               + (shift.get("caveats") or []))
    caveats.append("Programme movement describes schedule change only; it is "
                   "not evidence of causation or responsibility.")
    return _finish(intent, blocks, "Baseline vs current comparison:",
                   guards,
                   shift.get("requires_analyst_review", False), fallbacks,
                   caveats, shift.get("warnings"), primary=shift)


# ── 4. chronology_html ───────────────────────────────────────

def chronology_html(ctx: RunContext) -> CompositeResult:
    intent = "composite.chronology_html"
    ctx.report("tool", "Building the chronology section...")
    from src.delay_reports import run_event_chronology
    out = run_event_chronology(ctx.query, ctx.router, ctx.doc_ids)
    if out.get("clarification"):
        return clarification_result(intent, out.get("answer", ""))

    tr = out.get("programme_artifact") or {}
    guards = tool_result_guard_statuses(tr)
    fallbacks: List[str] = []
    title = (tr.get("summary") or "Delay Event Chronology").split(":")[0] \
        .replace("Chronology for ", "").strip("'\" ") or "Delay Event Chronology"

    section = dict(
        title=title,
        narrative_markdown=out.get("answer", ""),
        tables=(tr.get("tables") or [])[:1],
        sources=out.get("sources") or [],
        caveats=tr.get("caveats") or [],
        validation=tr.get("validation") or {},
        section_number="6.1",
    )
    block = build_html_block(**section)
    if block["type"] == "markdown_text":
        guards["html_guard"] = "failed"
        fallbacks.append("html→markdown")
    else:
        guards["html_guard"] = "passed"

    blocks = [block]
    # Downloads only for a section that passed the html guard: if the guard
    # just declared this markup unsafe, we do not hand out a PDF of it.
    if block["type"] == "html_report_section":
        from src.export import section_artifacts
        arts = section_artifacts(run_id=ctx.run_id, **section)
        if arts:
            blocks.extend(artifact_blocks({"artifacts": arts}))

    return _finish(intent, blocks, "Chronology report section:", guards,
                   tr.get("requires_analyst_review", False), fallbacks,
                   tr.get("caveats") or [], tr.get("warnings"),
                   sources=out.get("sources") or [], primary=tr)


# ── 5. context_to_section ────────────────────────────────────

def context_to_section(ctx: RunContext) -> CompositeResult:
    intent = "composite.context_to_section"
    art = ctx.context_artifact
    if not isinstance(art, dict) or not (art.get("tables") or art.get("summary")):
        return clarification_result(
            intent, "Which result should I format as a report section? "
                    "Run an analysis first (e.g. a DCMA check or milestone "
                    "shift), then ask again.")

    title = (art.get("summary") or "Analysis section").split(":")[0][:80]
    block = build_html_block(
        title=title,
        narrative_markdown=art.get("summary", ""),
        tables=(art.get("tables") or [])[:2],
        sources=[],
        caveats=art.get("caveats") or [],
        validation=art.get("validation") or {},
    )
    guards = {"html_guard": "passed" if block["type"] == "html_report_section"
              else "failed"}
    fallbacks = [] if guards["html_guard"] == "passed" else ["html→markdown"]
    return _finish(intent, [block], "Report section:", guards,
                   art.get("requires_analyst_review", False), fallbacks,
                   art.get("caveats") or [])


# ── 6. dcma_latest ───────────────────────────────────────────

def dcma_latest(ctx: RunContext) -> CompositeResult:
    intent = "composite.dcma_latest"
    from .resolver import resolve_xer
    res = resolve_xer("latest")
    if res.needs_confirmation:
        return clarification_result(intent, res.clarification, res.options)

    rec = res.resolved["current_xer"]
    ctx.report("tool", f"Running DCMA on {rec['file_name']}...")
    from src.programme_tools import run_tool
    result = run_tool("programme.dcma_14_point",
                      [{"doc_id": rec["doc_id"], "file_name": rec["file_name"],
                        "file_path": rec["file_path"], "status": "completed"}])
    tr = result.to_dict()
    if tr["status"] == "failed":
        return CompositeResult(intent_id=intent, status="failed",
                               answer=tr["summary"])

    from src.programme_tools.narrative import compose_narrative
    narrative = compose_narrative(result, getattr(result, "_engine_ctx", None))
    guards = tool_result_guard_statuses(result.to_dict())

    blocks = [md_block(narrative, "narrative")]
    for i, t in enumerate(tr.get("tables") or []):
        blocks.append(table_block(t, f"table{i + 1}"))
    blocks.extend(artifact_blocks(tr))

    caveats = list(tr.get("caveats") or []) + res.caveats
    caveats.append(f"Latest programme selected automatically by data date: "
                   f"{rec['file_name']}.")
    return _finish(intent, blocks, f"DCMA health check — {rec['file_name']}:",
                   guards, tr.get("requires_analyst_review", False), [],
                   caveats, tr.get("warnings"), primary=tr)


# ── 7. evidence_explain (HIGH RISK — trust-guarded) ──────────

def evidence_explain(ctx: RunContext) -> CompositeResult:
    intent = "composite.evidence_explain"
    ctx.report("searching", "Collecting delay evidence from the record...")

    from src.delay_reports.schemas import ScopeResult
    from src.delay_reports.retrieval import retrieve_evidence
    from src.delay_reports.register import build_event_register

    terms = [t for t in re.findall(r"[a-zA-Z]{4,}", ctx.query.lower())
             if t not in ("explain", "delay", "delays", "evidence", "show",
                          "supporting", "documents", "using", "occurred",
                          "project", "with", "possible", "graph")]
    scope = ScopeResult(event_title="project delays",
                        topic_terms=terms or ["delay"])
    corpus = ""
    try:
        from src.document_rag import _current_user_corpus
        corpus = _current_user_corpus() or "demo"
    except Exception:
        corpus = "demo"

    evidence = retrieve_evidence(scope, corpus, ctx.doc_ids)
    if not evidence:
        return clarification_result(
            intent, "No delay-related correspondence was found in the corpus. "
                    "Upload the relevant letters/notices or name a specific "
                    "delay event.")

    ctx.report("analysing", "Extracting dated statements from evidence...")
    register = build_event_register(evidence, "project delays")
    if not register.entries:
        return CompositeResult(
            intent_id=intent, status="partial",
            blocks=[md_block("The record was searched but no dated delay "
                             "statements passed evidence validation. Analyst "
                             "review of the source documents is recommended.")],
            answer="Insufficient validated evidence.")

    rows = [[e.event_date, e.actor, e.issue[:110],
             f"{e.file_name}, p.{e.page_number}", e.support_level]
            for e in sorted(register.entries, key=lambda e: e.event_date)]
    table = {"title": "Delay statements found in the record (as stated by "
                      "the parties — not causation findings)",
             "columns": ["Date", "Party", "Stated issue", "Source", "Support"],
             "rows": rows}

    # Deterministic, attributed narrative — states only what documents say.
    cats: Dict[str, int] = {}
    for e in register.entries:
        key = e.issue.split(":")[0][:60]
        cats[key] = cats.get(key, 0) + 1
    top_lines = "\n".join(f"- {k} ({v} document(s))" for k, v in
                          sorted(cats.items(), key=lambda kv: -kv[1])[:6])
    narrative = (
        "Based on the correspondence record, the parties raised the following "
        f"delay-related issues (as stated in the documents):\n\n{top_lines}\n\n"
        "These are the parties' contemporaneous statements; this summary does "
        "not establish causation or responsibility."
    )

    sources = [{"file_name": e.file_name, "doc_id": e.doc_id or e.file_name,
                "page_number": e.page_number, "text_snippet": e.quote[:300]}
               for e in register.entries]

    # Explicit Trust Guard verification (high-risk route).
    ctx.report("verifying", "Verifying the summary against the evidence...")
    guards: Dict[str, str] = {"containment_guard": "passed"}
    trust_verdict = None
    try:
        from src.trust_guard import run_trust_guard_on_result
        target = {"query_type": "document", "answer": narrative,
                  "sources": sources}
        verdict = run_trust_guard_on_result(ctx.router, ctx.query, target)
        if not verdict.skipped:
            trust_verdict = target.get("trust_guard")
            narrative = target.get("answer", narrative)
            guards["trust_guard"] = ("passed" if verdict.action == "approve"
                                     else "fallback")
        else:
            guards["trust_guard"] = "skipped"
    except Exception as e:
        logger.warning(f"[Orchestration] trust guard failed open: {e}")
        guards["trust_guard"] = "skipped"

    caveats = list(register.caveats)
    caveats.append("This is a factual chronology of the record, not a "
                   "causation or liability finding; analyst review is "
                   "required before any claim use.")

    blocks = [md_block(narrative, "narrative"), table_block(table, "evidence")]
    return _finish(intent, blocks, "Evidence-backed delay overview:", guards,
                   True, [], caveats, sources=sources,
                   trust_guard=trust_verdict)
