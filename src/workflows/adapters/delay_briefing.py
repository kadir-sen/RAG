"""delay_briefing workflow — MVP.

One prompt, the whole project picture: what data exists, what the programme
says, how milestones moved, which delay events are confirmed, whether notices
were served, and how the progress record looks — assembled from workflows that
already exist. No new computation lives here; this is composition.

Runs only what the data supports. A missing piece is named in the caveats, not
faked, and never blocks the rest. Preliminary and analyst-review-required
throughout: this is a briefing to orient a claim, not a finding on it.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from src.orchestration.helpers import md_block

from .. import caveats as CV
from ..blocks import content_blocks, corpus_id, finalize_blocks
from ..types import (
    RESULT_PARTIAL, RESULT_UNAVAILABLE, WorkflowId, WorkflowResult,
)

logger = logging.getLogger(__name__)


def _safe(label: str, fn, *args, **kw) -> Optional[WorkflowResult]:
    """Run a sub-workflow; a crash costs its section, not the briefing.

    The pieces this composes are individually defensive (run_composite and
    run_tool never raise), but the adapters in between are not, and a briefing
    that dies because one section threw is worse than a briefing missing that
    section.
    """
    try:
        return fn(*args, **kw)
    except Exception as e:
        logger.warning(f"[DelayBriefing] {label} failed: {e}", exc_info=True)
        return None


def _composite_blocks(intent_id: str, query: str, router: Any,
                      doc_ids: Optional[List[str]]) -> tuple:
    """Run a composite intent directly. Returns (blocks, caveats).

    The executor's _delegate_composite needs a WorkflowPlan and executor
    context that an adapter does not have, so this calls run_composite itself —
    which also brings that composite's own guards (chart_guard included) along
    for free. run_composite never raises.
    """
    try:
        from src.orchestration import run_composite
        res = run_composite(intent_id, query, {}, router, doc_ids)
    except Exception as e:                                   # pragma: no cover
        logger.warning(f"[DelayBriefing] {intent_id} unavailable: {e}")
        return [], []
    if res.status in ("failed", "needs_clarification"):
        return [], list(getattr(res, "caveats", None) or [])
    keep = {"markdown_text", "data_table", "chart", "artifact_link",
            "html_report_section"}
    blocks = [b for b in res.blocks if b.get("type") in keep]
    return blocks, list(getattr(res, "caveats", None) or [])


def run(query: str, router: Any = None, doc_ids: Optional[List[str]] = None
        ) -> WorkflowResult:
    wid = WorkflowId.DELAY_BRIEFING
    from src.delay_reports import candidate_store

    from . import (monthly_progress_report as _mpr,
                   notice_matrix as _nm,
                   programme_inventory as _pi)

    corpus = corpus_id()
    blocks: List[dict] = []
    caveats: List[str] = []
    sections: List[str] = []
    n = 0

    def heading(text: str) -> str:
        nonlocal n
        n += 1
        return f"## {n}. {text}"

    # 1. Programme summary — only when a programme actually exists.
    records = _safe("programme records",
                    lambda: router._programme_records() if router else []) or []
    if records:
        inv = _safe("programme inventory", _pi.run, query, router, doc_ids)
        if inv and inv.blocks:
            blocks.append(md_block(heading("Programme summary"), "s-programme"))
            blocks.extend(content_blocks(inv))
            caveats.extend(inv.caveats)
            sections.append("programme summary")

    # 2. Milestone movement — needs two dated revisions; the composite says so
    #    itself when it cannot run.
    if len(records) >= 2:
        ms_blocks, ms_caveats = _composite_blocks(
            "composite.milestone_shift_visual", query, router, doc_ids)
        if ms_blocks:
            blocks.append(md_block(heading("Milestone movement"), "s-milestone"))
            blocks.extend(ms_blocks)
            caveats.extend(ms_caveats)
            caveats.append(CV.MOVEMENT_NOT_CAUSATION)
            sections.append("milestone movement")
    elif records:
        caveats.append(CV.ONE_XER_ONLY)

    # 3. Confirmed delay events — analyst-confirmed only; candidates are not
    #    evidence and must not appear in a briefing.
    confirmed = _safe("confirmed events",
                      candidate_store.confirmed_events, corpus=corpus) or []
    if confirmed:
        rows = [[i + 1, c.get("event_date", ""), c.get("actor", ""),
                 (c.get("issue") or "")[:80],
                 f"{c.get('file_name', '')}, p.{c.get('page_number', '')}"]
                for i, c in enumerate(sorted(
                    confirmed, key=lambda c: c.get("event_date") or ""))]
        blocks.append(md_block(heading("Confirmed delay events"), "s-events"))
        blocks.append({"type": "data_table", "block_id": "events",
                       "title": "Confirmed delay events",
                       "columns": ["#", "Date", "Party", "Issue", "Source"],
                       "rows": rows, "caption": ""})
        sections.append("confirmed delay events")

        # 4. Notice compliance — meaningless without confirmed events.
        nmx = _safe("notice matrix", _nm.run, query, router, doc_ids)
        if nmx and nmx.blocks:
            blocks.append(md_block(heading("Notice compliance"), "s-notice"))
            blocks.extend(content_blocks(nmx))
            caveats.extend(nmx.caveats)
            sections.append("notice compliance")
    else:
        caveats.append("No analyst-confirmed delay events are on record, so "
                       "the briefing carries no delay-event or notice section; "
                       "run the candidate delay event register and confirm "
                       "events first.")

    # 5. Progress record — the whole monthly report, minus its own lead line.
    mpr = _safe("monthly progress report", _mpr.run, query, router, doc_ids)
    if mpr and mpr.status != RESULT_UNAVAILABLE:
        prog = [b for b in content_blocks(mpr) if b.get("block_id") != "lead"]
        if prog:
            blocks.append(md_block(heading("Progress record"), "s-progress"))
            blocks.extend(prog)
            caveats.extend(mpr.caveats)
            sections.append("progress record")
    elif mpr:
        caveats.extend(mpr.caveats)

    if not sections:
        text = ("A delay briefing needs a programme (.xer), confirmed delay "
                "events, or progress data. None of those are loaded yet — "
                "upload a programme or the progress workbooks to start.")
        return WorkflowResult(
            workflow_id=wid, status=RESULT_UNAVAILABLE, answer=text,
            blocks=[md_block(text, "empty")], caveats=caveats,
            substitute=WorkflowId.PRELIMINARY_PROGRAMME_PACK.value)

    lead = ("**Monthly progress and delay briefing** — assembled from: "
            + ", ".join(sections) + ". Preliminary and for analyst review; "
            "not a submission, a finding, or an assessment of entitlement.")
    blocks = [md_block(lead, "lead")] + blocks

    caveats = CV.aggregate(caveats, [CV.CHRONOLOGY_PRELIMINARY,
                                     CV.ANALYST_REVIEW_ENTITLEMENT])
    blocks = finalize_blocks(blocks, {"briefing": "assembled"}, True, [],
                             caveats)
    return WorkflowResult(
        workflow_id=wid, status=RESULT_PARTIAL, blocks=blocks, answer=lead,
        caveats=caveats, analyst_review_required=True,
        validation={"briefing": "assembled"})
