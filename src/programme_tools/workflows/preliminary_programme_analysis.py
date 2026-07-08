"""Workflow: report.preliminary_programme_analysis_pack

Deterministic step plan (NOT LLM-chosen): inventory → DCMA per revision →
milestone shift when >=2 dated revisions → per-section narrative + guard.
DOCX/PDF assembly is deferred to the report-pack sprint; the pack ships as
structured sections the chat UI renders.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

from ..executor import run_tool
from ..narrative import compose_narrative
from ..schemas import STATUS_COMPLETE

logger = logging.getLogger(__name__)

WORKFLOW_ID = "report.preliminary_programme_analysis_pack"
_DCMA_CAP = 6


def _noop_progress(kind: str, label: str, detail: str = "") -> None:
    return None


def run_pack(records: List[Dict[str, Any]],
             progress: Optional[Callable[..., None]] = None,
             use_llm: bool = True) -> Dict[str, Any]:
    """Run the full pack. Returns {pack_id, status, sections, assembly}."""
    report = progress or _noop_progress
    pack_id = uuid.uuid4().hex[:12]
    sections: List[Dict[str, Any]] = []
    statuses: List[str] = []

    def _section(section_id: str, title: str, tool_id: str,
                 recs: List[Dict[str, Any]], options=None) -> None:
        report("tool", f"Running {title}...")
        result = run_tool(tool_id, recs, options=options,
                          run_id=f"{pack_id}-{section_id}")
        narrative = compose_narrative(
            result, getattr(result, "_engine_ctx", None), use_llm=use_llm)
        sections.append({
            "section_id": section_id,
            "title": title,
            "tool_result": result.to_dict(),
            "narrative": narrative,
        })
        statuses.append(result.status)

    # 1. Inventory — always first; every downstream section leans on it.
    _section("inventory", "Programme Inventory", "programme.inventory", records)

    # 2. DCMA per revision (capped).
    capped = records[:_DCMA_CAP]
    for i, rec in enumerate(capped, start=1):
        name = rec.get("file_name", f"revision {i}")
        _section(f"dcma_{i}", f"DCMA 14-Point — {name}",
                 "programme.dcma_14_point", [rec])
    if len(records) > _DCMA_CAP:
        sections.append({
            "section_id": "dcma_cap_note",
            "title": "DCMA coverage note",
            "tool_result": None,
            "narrative": (f"Only the first {_DCMA_CAP} of {len(records)} "
                          "revisions received a DCMA assessment in this pack."),
        })
        statuses.append("partial")

    # 3. Milestone shift when at least two revisions exist.
    if len(records) >= 2:
        _section("milestone_shift", "Milestone Shift Tracker",
                 "programme.milestone_shift", records)
    else:
        sections.append({
            "section_id": "milestone_shift",
            "title": "Milestone Shift Tracker",
            "tool_result": None,
            "narrative": ("Milestone shift tracking requires at least two XER "
                          "revisions; only one is available, so this section "
                          "was skipped."),
        })
        statuses.append("partial")

    status = STATUS_COMPLETE if all(s == STATUS_COMPLETE for s in statuses) else "partial"
    report("answer", "Assembling preliminary programme analysis pack...")
    return {
        "pack_id": pack_id,
        "workflow_id": WORKFLOW_ID,
        "status": status,
        "sections": sections,
        "assembly": {
            "format": "sections_json",
            "note": "DOCX/PDF assembly deferred to the report-pack sprint.",
        },
    }
