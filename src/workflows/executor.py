"""Workflow executor.

Resolves inputs, prepends the Input-Resolution-Summary, delegates available
workflows to existing composite runners or adapters, returns structured
"planned/unavailable" responses, aggregates caveats, and converts everything to
the existing chat-block response contract. Never raises; never surfaces a raw
provider error.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from . import caveats as CV
from . import context as CTX
from .adapters import (
    delay_chronology as _adp_chronology,
    preliminary_pack as _adp_pack,
    programme_inventory as _adp_inventory,
)
from .registry import WORKFLOWS, WorkflowSpec, get_spec
from .types import (
    RESULT_CLARIFICATION, RESULT_FAILED, RESULT_PARTIAL, RESULT_SUCCESS,
    RESULT_UNAVAILABLE, WorkflowContext, WorkflowId, WorkflowPlan,
    WorkflowResult, WorkflowStatus,
)

logger = logging.getLogger(__name__)

# Catalogue caveats injected per workflow (on top of runner/adapter caveats).
_EXTRA_CAVEATS: Dict[WorkflowId, List[str]] = {
    WorkflowId.DCMA_LATEST: [CV.DCMA_HEALTH_NOT_DELAY],
    WorkflowId.MILESTONE_SHIFT_CHART: [CV.MOVEMENT_NOT_CAUSATION],
    WorkflowId.DELAY_CHRONOLOGY_SECTION: [CV.CHRONOLOGY_PRELIMINARY,
                                          CV.ANALYST_REVIEW_ENTITLEMENT],
}

_COMPOSITE_STATUS = {
    "success": RESULT_SUCCESS, "partial": RESULT_PARTIAL,
    "needs_clarification": RESULT_CLARIFICATION, "failed": RESULT_FAILED,
}


# ── block helpers ────────────────────────────────────────────

def _caveats_from_blocks(blocks: List[dict]) -> List[str]:
    for b in blocks:
        if b.get("type") == "caveats":
            return list(b.get("caveats") or [])
    return []


def _guards_from_blocks(blocks: List[dict]) -> Dict[str, str]:
    for b in blocks:
        if b.get("type") == "validation_status":
            return dict(b.get("guards") or {})
    return {}


def _analyst_from_blocks(blocks: List[dict]) -> bool:
    return any(b.get("type") == "validation_status"
               and b.get("requires_analyst_review") for b in blocks)


def _merge_extra_caveats(blocks: List[dict], extra: List[str]) -> None:
    """Fold catalogue caveats into the single existing caveats block (or
    insert one just before validation_status). Mutates blocks in place."""
    extra = [c for c in extra if c]
    if not extra:
        return
    for b in blocks:
        if b.get("type") == "caveats":
            merged = CV.aggregate(b.get("caveats") or [], extra)
            b["caveats"] = merged
            return
    # No caveats block yet — insert before validation_status if present.
    cb = {"type": "caveats", "block_id": "caveats",
          "caveats": CV.aggregate(extra), "warnings": []}
    for i, b in enumerate(blocks):
        if b.get("type") == "validation_status":
            blocks.insert(i, cb)
            return
    blocks.append(cb)


# ── unavailable / clarification builders ─────────────────────

def _unavailable_result(spec: WorkflowSpec, query: str) -> WorkflowResult:
    sub = WORKFLOWS.get(spec.substitute) if spec.substitute else None
    lines = [f"**{spec.name}** is planned but not built yet."]
    if spec.required_inputs:
        lines.append("\nIt will need: " + ", ".join(spec.required_inputs) + ".")
    if spec.runnable_now:
        lines.append("\nYou can run now: " + ", ".join(spec.runnable_now) + ".")
    if sub:
        hint = spec.substitute_hint or sub.name
        lines.append(f"\nClosest available analysis — **{sub.name}**: "
                     f"try \"{hint}\".")
    elif spec.substitute_hint:
        lines.append(f"\nAvailable substitute: {spec.substitute_hint}.")
    text = " ".join(lines)
    return WorkflowResult(
        workflow_id=spec.workflow_id, status=RESULT_UNAVAILABLE,
        answer=text,
        blocks=[{"type": "markdown_text", "block_id": "unavailable",
                 "text": text}],
        substitute=spec.substitute.value if spec.substitute else None,
    )


def _clarification_result(wid: WorkflowId, question: str,
                          options: Optional[List[dict]] = None) -> WorkflowResult:
    return WorkflowResult(
        workflow_id=wid, status=RESULT_CLARIFICATION, answer=question,
        blocks=[{"type": "clarification", "block_id": "clarify",
                 "question": question, "options": options or []}],
    )


# ── main entry ───────────────────────────────────────────────

def run_workflow(plan: WorkflowPlan, query: str, router: Any,
                 doc_ids: Optional[List[str]] = None,
                 context_artifact: Optional[dict] = None) -> WorkflowResult:
    """Execute one registered workflow. Never raises."""
    started = time.time()
    spec = get_spec(plan.workflow_id)
    ctx = CTX.build_context(query, router, doc_ids, context_artifact)
    try:
        if spec is None:
            wr = WorkflowResult(workflow_id=plan.workflow_id,
                                status=RESULT_FAILED,
                                answer="Unknown workflow.")
        elif spec.status in (WorkflowStatus.PLANNED, WorkflowStatus.UNAVAILABLE):
            wr = _unavailable_result(spec, query)
        else:
            wr = _run_available(spec, plan, query, router, doc_ids,
                                context_artifact, ctx)
    except Exception as e:  # no raw provider error ever reaches chat
        logger.exception(f"[Workflow] {plan.workflow_id} crashed")
        wr = WorkflowResult(
            workflow_id=plan.workflow_id, status=RESULT_FAILED,
            answer="That analysis could not be completed; please try again.",
            debug_trace={"error": str(e)[:200]})

    _record_telemetry(wr, ctx, plan, started, doc_ids)
    return wr


def _run_available(spec: WorkflowSpec, plan: WorkflowPlan, query: str,
                   router: Any, doc_ids: Optional[List[str]],
                   context_artifact: Optional[dict],
                   ctx: WorkflowContext) -> WorkflowResult:
    wid = spec.workflow_id

    # 1) Resolve formal inputs first (deterministic, no side effects).
    res = CTX.resolve_inputs(wid, query, router, doc_ids, context_artifact)
    if res.get("needs_confirmation"):
        return _clarification_result(wid, res.get("clarification", ""),
                                     res.get("options"))

    # 1b) Document-selection memory (project-scoped) — a VISIBLE hint only.
    #     A previously-approved selection is surfaced in the input summary for
    #     the user to confirm; it is never silently reused.
    dm_key, dm_hit = _document_memory_hint(wid, query, router, ctx, res)

    # 2) Delegate to composite runner or adapter.
    target = spec.target or ""
    if wid == WorkflowId.DELAY_CHRONOLOGY_SECTION and \
            plan.params.get("mode") == "html":
        wr = _delegate_composite(wid, "composite.chronology_html", query,
                                 plan, router, doc_ids, context_artifact)
    elif target.startswith("composite:"):
        wr = _delegate_composite(wid, target.split(":", 1)[1], query, plan,
                                 router, doc_ids, context_artifact)
    elif target == "adapter:programme_inventory":
        wr = _adp_inventory.run(query, router, doc_ids)
    elif target == "adapter:preliminary_pack":
        wr = _adp_pack.run(query, router, doc_ids)
    elif target == "adapter:delay_chronology":
        wr = _adp_chronology.run(query, router, doc_ids)
    elif target == "adapter:candidate_register":
        from .adapters import candidate_register as _adp_candidates
        wr = _adp_candidates.run(query, router, doc_ids)
    elif target == "adapter:event_evidence_table":
        from .adapters import event_evidence_table as _adp_evidence
        wr = _adp_evidence.run(query, router, doc_ids)
    elif target == "adapter:notice_matrix":
        from .adapters import notice_matrix as _adp_notice
        wr = _adp_notice.run(query, router, doc_ids)
    elif target == "adapter:contract_mechanism":
        from .adapters import contract_mechanism as _adp_contract
        wr = _adp_contract.run(query, router, doc_ids)
    elif target == "adapter:method_viability":
        from .adapters import method_viability as _adp_method
        wr = _adp_method.run(query, router, doc_ids)
    elif target == "adapter:delay_claim_pack":
        from .adapters import delay_claim_pack as _adp_pack2
        wr = _adp_pack2.run(query, router, doc_ids)
    elif target == "adapter:monthly_progress_report":
        from .adapters import monthly_progress_report as _adp_monthly
        wr = _adp_monthly.run(query, router, doc_ids)
    elif target == "adapter:delay_briefing":
        from .adapters import delay_briefing as _adp_briefing
        wr = _adp_briefing.run(query, router, doc_ids)
    elif target == "adapter:programme_variance":
        from .adapters.programme_tool_workflow import run_programme_tool_workflow
        wr = run_programme_tool_workflow(
            WorkflowId.PROGRAMME_VARIANCE, "programme.variance", router,
            doc_ids, min_files=2,
            need_message="As-planned vs as-recorded variance needs a baseline "
                         "and a later dated .xer revision (at least two).")
    elif target == "adapter:programme_critical_path":
        from .adapters.programme_tool_workflow import run_programme_tool_workflow
        wr = run_programme_tool_workflow(
            WorkflowId.PROGRAMME_CRITICAL_PATH, "programme.critical_path",
            router, doc_ids, min_files=1,
            need_message="Critical path analysis needs a programme .xer file.")
    elif target == "adapter:programme_comparison":
        from .adapters.programme_tool_workflow import run_programme_tool_workflow
        wr = run_programme_tool_workflow(
            WorkflowId.PROGRAMME_COMPARISON, "programme.comparison", router,
            doc_ids, min_files=2,
            need_message="Revision comparison needs two dated .xer revisions.")
    else:
        return WorkflowResult(workflow_id=wid, status=RESULT_FAILED,
                              answer="No handler for this workflow.")

    # 3) Clarification / pointer messages from a delegated runner: pass through.
    if wr.status in (RESULT_CLARIFICATION, RESULT_UNAVAILABLE):
        return wr

    # 4) Fold in catalogue caveats + prepend the input-resolution summary.
    _merge_extra_caveats(wr.blocks, _EXTRA_CAVEATS.get(wid, []))
    wr.caveats = CV.aggregate(wr.caveats, _caveats_from_blocks(wr.blocks),
                              res.get("caveats") or [])
    analyst = wr.analyst_review_required or _analyst_from_blocks(wr.blocks)
    wr.analyst_review_required = analyst
    summary = CTX.input_resolution_block(res.get("lines") or [],
                                         res.get("caveats") or [],
                                         res.get("missing") or [], analyst)
    if summary:
        wr.blocks = [summary] + wr.blocks
        wr.selected_inputs_summary = summary["text"]
    if not wr.validation:
        wr.validation = _guards_from_blocks(wr.blocks)

    # Record the selection this run used, so a future run can offer it (only
    # after approval). Best-effort; never affects the result.
    wr.debug_trace["memory_hint_used"] = dm_hit
    if dm_key and doc_ids and wr.status in (RESULT_SUCCESS, RESULT_PARTIAL):
        try:
            from src.learning import document_memory as _dm
            _dm.record_selection(dm_key, list(doc_ids), corpus=ctx.corpus_id)
        except Exception:
            pass
    return wr


# Workflows whose input is a document selection (project-scoped memory applies).
_DOC_MEMORY_WORKFLOWS = {
    WorkflowId.DELAY_EVENT_CANDIDATE_REGISTER,
    WorkflowId.EVENT_EVIDENCE_TABLE,
    WorkflowId.DELAY_CHRONOLOGY_SECTION,
}


def _document_memory_hint(wid: WorkflowId, query: str, router: Any,
                          ctx: WorkflowContext, res: dict):
    """Surface a previously-approved document selection as a visible hint in the
    input-resolution summary. Returns (analysis_key, hit_bool). Never raises."""
    if wid not in _DOC_MEMORY_WORKFLOWS:
        return None, False
    try:
        from src.learning import document_memory as dm
        title = ""
        try:
            from src.delay_reports.scope import resolve_event_scope
            title = (resolve_event_scope(query, router).event_title or "").strip()
        except Exception:
            title = ""
        akey = dm.analysis_key(wid.value, title)
        hint = dm.suggest(akey, corpus=ctx.corpus_id)
        if hint and hint.get("doc_ids"):
            res.setdefault("lines", []).append(
                f"- Previously approved documents for this analysis: "
                f"{len(hint['doc_ids'])} — reuse? (confirm to apply)")
            return akey, True
        return akey, False
    except Exception:
        return None, False


def _delegate_composite(wid: WorkflowId, composite_id: str, query: str,
                        plan: WorkflowPlan, router: Any,
                        doc_ids: Optional[List[str]],
                        context_artifact: Optional[dict]) -> WorkflowResult:
    from src.orchestration import run_composite
    cr = run_composite(composite_id, query, plan.params, router, doc_ids,
                       context_artifact)
    status = _COMPOSITE_STATUS.get(cr.status, RESULT_FAILED)
    if status == RESULT_CLARIFICATION:
        return WorkflowResult(workflow_id=wid, status=status,
                              answer=cr.answer, blocks=cr.blocks)
    return WorkflowResult(
        workflow_id=wid, status=status, blocks=list(cr.blocks),
        answer=cr.answer, sources=cr.sources,
        primary_artifact=cr.primary_artifact, trust_guard=cr.trust_guard,
        caveats=_caveats_from_blocks(cr.blocks),
        analyst_review_required=_analyst_from_blocks(cr.blocks),
        validation=_guards_from_blocks(cr.blocks),
    )


# ── response-contract boundary ───────────────────────────────

def workflow_result_to_response(wr: WorkflowResult) -> Dict[str, Any]:
    """Convert a WorkflowResult to the router response dict (same shape as
    _handle_composite_query), so the response builder needs no changes."""
    out: Dict[str, Any] = {
        "answer": wr.answer,
        "query_type": "workflow",
        "blocks": wr.blocks,
        "sources": wr.sources,
        "workflow_id": wr.workflow_id.value,
    }
    if wr.status in (RESULT_CLARIFICATION,):
        out["clarification"] = True
    if wr.primary_artifact:
        out["programme_artifact"] = wr.primary_artifact
    if wr.trust_guard:
        out["trust_guard"] = wr.trust_guard
    return out


def _record_telemetry(wr: WorkflowResult, ctx: WorkflowContext,
                      plan: WorkflowPlan, started: float,
                      doc_ids: Optional[List[str]]) -> None:
    try:
        from src.learning.workflow_telemetry import record_workflow_run
        ctx.selected_documents = list(doc_ids or [])
        ctx.analyst_review_required = wr.analyst_review_required
        ctx.caveats = wr.caveats
        record_workflow_run(wr, ctx, plan,
                            latency_ms=(time.time() - started) * 1000.0)
    except Exception as e:
        logger.debug(f"[Workflow] telemetry skipped: {e}")
