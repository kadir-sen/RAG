"""The evidence pack: what a chronology was actually allowed to read.

Both chronology pipelines used to describe their own coverage from whatever
retrieval surfaced, not from the evidence they ended up reading, and neither
recorded how big that evidence was. A production report that read 24,500
characters of a 240,000,000-character corpus and dropped most of its extraction
batches was therefore indistinguishable from a complete one: three events,
`coverage_status: "complete"`, no error.

This module owns the two answers that ambiguity needs — what is in the pack, and
whether the pack was enough — so v2 and v3 give the same answer to both.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence

from .evidence_model import EvidenceItem


# Below this many dated events the record is reported as partial. The authored
# reports under content/chronologies carry 9-18 events and the prompt asks for
# 8-18. This is a floor for honest labelling, not a quota: a sparse record still
# ships, it just stops claiming to be a full one.
THIN_RECORD_EVENTS = 8


@dataclass(frozen=True)
class PackAssessment:
    status: str                                   # "complete" | "partial"
    reasons: List[str] = field(default_factory=list)
    pack: Dict = field(default_factory=dict)


def describe_pack(evidence: Sequence[EvidenceItem],
                  extraction_stats: Dict | None = None) -> Dict:
    """Measurable facts about the evidence the model was given.

    `documents` counts distinct file names and `fragments` distinct doc_ids
    because those are not the same thing: in production one file averages ~14
    doc_ids, so a "twelve document" selection was really twelve fragments.
    Reporting both makes that visible instead of implied.
    """
    stats = extraction_stats or {}
    return {
        "documents": len({item.file_name for item in evidence if item.file_name}),
        "fragments": len({item.doc_id for item in evidence if item.doc_id}),
        "passages": len(evidence),
        "chars": sum(len(item.excerpt or "") for item in evidence),
        "batches_total": int(stats.get("batches_total", 0)),
        "batches_failed": int(stats.get("batches_failed", 0)),
        "passages_dropped": int(stats.get("passages_dropped", 0)),
        "batch_errors": list(stats.get("batch_errors", [])),
    }


def assess_pack(*, evidence: Sequence[EvidenceItem], event_count: int,
                coverage: Dict[str, int],
                extraction_stats: Dict | None = None) -> PackAssessment:
    """Whether the record may call itself complete, and why not if it may not.

    `coverage` must be measured over the pack itself. Measuring it over
    everything retrieval surfaced — which is what the preview does — lets a
    facet count as covered by a document that was never read.
    """
    pack = describe_pack(evidence, extraction_stats)
    pack["events"] = int(event_count)

    reasons: List[str] = []
    if any(hits == 0 for hits in (coverage or {}).values()):
        reasons.append("uncovered_facets")
    if pack["batches_failed"]:
        reasons.append("evidence_extraction_incomplete")
    if event_count < THIN_RECORD_EVENTS:
        reasons.append("thin_record")

    return PackAssessment(
        status="complete" if not reasons else "partial",
        reasons=reasons, pack=pack,
    )


__all__ = ["PackAssessment", "THIN_RECORD_EVENTS", "assess_pack", "describe_pack"]
