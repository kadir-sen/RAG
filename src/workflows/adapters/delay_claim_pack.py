"""preliminary_delay_claim_pack workflow — MVP.

Assembles the available claim-preparation pieces into one preliminary pack:
programme inventory + confirmed delay events + notice compliance matrix +
method-viability screen. Runs only what the data supports; missing pieces are
noted, not faked. Preliminary and analyst-review-required throughout — this is
a working draft to structure the claim, not a submission or a finding.
"""

from __future__ import annotations

from typing import Any, List, Optional

from src.orchestration.helpers import md_block

from .. import caveats as CV
from ..blocks import finalize_blocks
from ..types import (
    RESULT_PARTIAL, RESULT_UNAVAILABLE, WorkflowId, WorkflowResult,
)

_CONTENT_TYPES = {"markdown_text", "data_table", "chart", "artifact_link",
                  "html_report_section"}


def _corpus() -> str:
    try:
        from src.document_rag import _current_user_corpus
        return _current_user_corpus() or "demo"
    except Exception:
        return "demo"


def _content_blocks(wr: WorkflowResult) -> List[dict]:
    """Content blocks of a sub-result (drop its input-summary/caveats/validation
    — the pack aggregates those once)."""
    return [b for b in wr.blocks
            if b.get("type") in _CONTENT_TYPES
            and b.get("block_id") != "input_resolution"]


def run(query: str, router: Any, doc_ids: Optional[List[str]] = None
        ) -> WorkflowResult:
    wid = WorkflowId.PRELIMINARY_DELAY_CLAIM_PACK
    from src.delay_reports import candidate_store
    from . import (method_viability as _mv, notice_matrix as _nm,
                   programme_inventory as _pi)

    corpus = _corpus()
    blocks: List[dict] = []
    caveats: List[str] = []
    sections: List[str] = []
    analyst = True

    # 1. Programme inventory (if any XER present).
    recs = router._programme_records() if router else []
    if recs:
        inv = _pi.run(query, router, doc_ids)
        blocks.append(md_block("## 1. Programme inventory", "s1"))
        blocks.extend(_content_blocks(inv))
        caveats.extend(inv.caveats)
        sections.append("programme inventory")

    # 2. Confirmed delay events.
    confirmed = candidate_store.confirmed_events(corpus=corpus)
    if confirmed:
        rows = [[i + 1, c.get("event_date", ""), c.get("actor", ""),
                 (c.get("issue") or "")[:80],
                 f"{c.get('file_name', '')}, p.{c.get('page_number', '')}"]
                for i, c in enumerate(sorted(confirmed,
                                             key=lambda c: c.get("event_date") or ""))]
        blocks.append(md_block("## 2. Confirmed delay events", "s2"))
        blocks.append({"type": "data_table", "block_id": "events",
                       "title": "Confirmed delay events",
                       "columns": ["#", "Date", "Party", "Issue", "Source"],
                       "rows": rows, "caption": ""})
        sections.append("confirmed events")

        # 3. Notice compliance matrix (needs confirmed events).
        nmx = _nm.run(query, router, doc_ids)
        blocks.append(md_block("## 3. Notice compliance", "s3"))
        blocks.extend(_content_blocks(nmx))
        caveats.extend(nmx.caveats)
        sections.append("notice matrix")

    # 4. Method viability (always informative).
    mv = _mv.run(query, router, doc_ids)
    blocks.append(md_block("## 4. Method viability", "s4"))
    blocks.extend(_content_blocks(mv))
    caveats.extend(mv.caveats)
    sections.append("method viability")

    if not recs and not confirmed:
        text = ("A preliminary delay claim pack needs at least a programme "
                "(.xer) or confirmed delay events. Upload a programme and run "
                "the *candidate delay event register* (then confirm events).")
        return WorkflowResult(
            workflow_id=wid, status=RESULT_UNAVAILABLE, answer=text,
            blocks=[md_block(text, "empty")],
            substitute=WorkflowId.DELAY_EVENT_CANDIDATE_REGISTER.value)

    lead = ("**Preliminary delay claim pack** — a working draft assembling: "
            + ", ".join(sections) + ". Preliminary and for analyst review; not "
            "a submission or a finding.")
    blocks = [md_block(lead, "lead")] + blocks
    caveats = CV.aggregate(caveats, [CV.CHRONOLOGY_PRELIMINARY,
                                     CV.ANALYST_REVIEW_ENTITLEMENT])
    blocks = finalize_blocks(blocks, {"pack": "assembled"}, analyst, [], caveats)
    return WorkflowResult(
        workflow_id=wid, status=RESULT_PARTIAL, blocks=blocks, answer=lead,
        caveats=caveats, analyst_review_required=True,
        validation={"pack": "assembled"})
