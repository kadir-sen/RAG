"""WorkflowContext construction + the Input-Resolution-Summary block.

There is no dedicated input_summary block type (validate_blocks would drop it),
so the summary renders as a compact markdown_text block. Input resolution is
deterministic and reuses the orchestration resolver — no LLM, no side effects.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from .types import WorkflowContext, WorkflowId

logger = logging.getLogger(__name__)


def _current_corpus() -> str:
    try:
        from src.document_rag import _current_user_corpus
        return _current_user_corpus() or ""
    except Exception:
        return ""


def build_context(query: str, router: Any, doc_ids: Optional[List[str]],
                  context_artifact: Optional[dict]) -> WorkflowContext:
    """Assemble the read-only context object for a run."""
    return WorkflowContext(
        user_query=query,
        corpus_id=_current_corpus(),
        selected_files=list(doc_ids or []),
        selected_documents=list(doc_ids or []),
        intermediate_outputs={"context_artifact": context_artifact}
        if context_artifact else {},
    )


def resolve_inputs(workflow_id: WorkflowId, query: str, router: Any,
                   doc_ids: Optional[List[str]],
                   context_artifact: Optional[dict]) -> Dict[str, Any]:
    """Resolve the formal inputs a workflow needs, deterministically.

    Returns a dict: {resolved, caveats, missing, needs_confirmation,
    clarification, options, lines}. `lines` is the human-readable summary body.
    Never raises — a resolver failure degrades to an empty summary.
    """
    out: Dict[str, Any] = {"resolved": {}, "caveats": [], "missing": [],
                           "needs_confirmation": False, "clarification": "",
                           "options": [], "lines": []}
    corpus = _current_corpus()
    try:
        if workflow_id in (WorkflowId.PROGRAMME_INVENTORY,
                           WorkflowId.PROJECT_DATA_INVENTORY,
                           WorkflowId.PRELIMINARY_PROGRAMME_PACK,
                           WorkflowId.MILESTONE_SHIFT_CHART):
            recs = router._programme_records(doc_ids) if router else []
            names = [r.get("file_name", "?") for r in recs]
            out["resolved"]["programme_files"] = names
            out["lines"].append(
                f"- Programme files: {len(names)}"
                + (f" ({', '.join(names[:4])}{'…' if len(names) > 4 else ''})"
                   if names else " — none uploaded"))
            if workflow_id == WorkflowId.MILESTONE_SHIFT_CHART and len(recs) < 2:
                out["needs_confirmation"] = True
                out["clarification"] = (
                    "Milestone shift tracking requires at least two XER "
                    f"revisions; currently {len(recs)} available. Please "
                    "upload the missing programme file(s).")
            elif not recs:
                out["needs_confirmation"] = True
                out["clarification"] = (
                    "Please upload at least one XER programme file to run "
                    "this analysis.")

        elif workflow_id == WorkflowId.DCMA_LATEST:
            from src.orchestration.resolver import resolve_xer
            res = resolve_xer("latest")
            out["caveats"] = list(res.caveats)
            if res.needs_confirmation:
                out.update(needs_confirmation=True,
                           clarification=res.clarification,
                           options=res.options)
            else:
                rec = res.resolved.get("current_xer") or {}
                dd = (rec.get("meta", {}) or {}).get("data_date", "")[:10]
                out["resolved"]["current_xer"] = rec.get("file_name", "")
                out["lines"].append(
                    f"- Latest programme: `{rec.get('file_name', '?')}`"
                    + (f" (data date {dd})" if dd else ""))

        elif workflow_id == WorkflowId.SQL_METRIC_CHART:
            from src.orchestration.resolver import resolve_table_period
            res = resolve_table_period(query, corpus)
            out["caveats"] = list(res.caveats)
            if res.needs_confirmation:
                out.update(needs_confirmation=True,
                           clarification=res.clarification,
                           options=res.options)
            else:
                schema = res.resolved.get("schema", "")
                tables = res.resolved.get("tables", [])
                period = res.resolved.get("period")
                out["resolved"].update(schema=schema, tables=tables,
                                       period=period)
                out["lines"].append(f"- Data schema: {schema} "
                                    f"({len(tables)} compatible table(s))")
                if period:
                    out["lines"].append(f"- Period: {period['date_key']}")

        elif workflow_id == WorkflowId.DELAY_CHRONOLOGY_SECTION:
            out["resolved"]["corpus"] = corpus or "demo"
            out["lines"].append(
                f"- Evidence corpus: {corpus or 'demo'}")
            if doc_ids:
                out["lines"].append(
                    f"- Scoped documents: {len(doc_ids)}")

        elif workflow_id == WorkflowId.CONTEXT_TO_REPORT_SECTION:
            has = isinstance(context_artifact, dict) and (
                context_artifact.get("tables") or context_artifact.get("summary"))
            out["resolved"]["has_context"] = bool(has)
            out["lines"].append(
                "- Source: previous analysis result"
                if has else "- Source: none (run an analysis first)")
            if not has:
                out["needs_confirmation"] = True
                out["clarification"] = (
                    "Which result should I format as a report section? Run an "
                    "analysis first (e.g. a DCMA check or milestone shift), "
                    "then ask again.")
    except Exception as e:  # resolver problems never break the workflow
        logger.debug(f"[Workflow] input resolution degraded: {e}")
    return out


def input_resolution_block(lines: List[str], caveats: List[str],
                           missing: List[str],
                           analyst_review: bool = False) -> Optional[dict]:
    """Compact markdown_text summary of which inputs were used/missing."""
    body: List[str] = ["**Input resolution summary**"]
    body.extend(lines or ["- (no formal inputs resolved)"])
    if missing:
        body.append(f"- Missing: {', '.join(missing)}")
    amb = [c for c in (caveats or []) if "confirm" in c.lower()
           or "ambiguous" in c.lower()]
    if amb:
        body.append(f"- Ambiguities: {amb[0]}")
    if analyst_review:
        body.append("- Analyst confirmation required: yes")
    return {"type": "markdown_text", "block_id": "input_resolution",
            "text": "\n".join(body)}
