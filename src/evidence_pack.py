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

import re
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Sequence

from .evidence_model import EvidenceItem


# Below this many dated events the record is reported as partial. The authored
# reports under content/chronologies carry 9-18 events and the prompt asks for
# 8-18. This is a floor for honest labelling, not a quota: a sparse record still
# ships, it just stops claiming to be a full one.
THIN_RECORD_EVENTS = 8

# Ceiling on the evidence handed to extraction, in characters. Three batches at
# EVIDENCE_BATCH_CHARS. The old rule capped the *count* of selected documents at
# twelve, which controlled neither cost nor truncation risk: a document here can
# be 16 characters or 290,000, so twelve of them was anywhere between one batch
# and fifty. Bounding the text bounds both.
MAX_PACK_CHARS = 240_000

# No single file may take more than this share of the budget. One 1.8 MB inquiry
# report would otherwise crowd out every contemporaneous letter — and a
# chronology is built from the letters.
MAX_DOCUMENT_SHARE = 0.25

# Keep passages scoring at least this fraction of the best one. Scores are
# ordinal (see ai_reports._rank_normalised), so this is "ranked respectably by
# some lane", not a calibrated probability. It is what makes the pack adaptive:
# a narrow topic runs out of qualifying passages early and costs less, while a
# broad one fills the budget.
RELEVANCE_FLOOR = 0.35

# Stop once the evidence stops telling us anything new: if this many
# consecutive passages bring neither a new facet nor a date the pack has not
# already seen, the rest is padding. A
# chronology is a list of dated events, so a passage that repeats dates we hold
# adds nothing to the record however relevant it looks — and a new *document*
# is deliberately not enough on its own, or a large diverse corpus would never
# saturate. The budget is a ceiling, not a target: a topic answered by 70,000
# characters should cost 70,000 characters.
SATURATION_WINDOW = 25

# How many scored passages retrieval hands to the selector. This is a candidate
# pool, not the pack: the selector still has to fit them inside MAX_PACK_CHARS.
# It was 120, which at a 1,200-character excerpt could not fill the budget even
# in principle, so the ceiling would never have been reachable.
CANDIDATE_PASSAGES = 400


@dataclass(frozen=True)
class PackAssessment:
    status: str                                   # "complete" | "partial"
    reasons: List[str] = field(default_factory=list)
    pack: Dict = field(default_factory=dict)


@dataclass(frozen=True)
class PackSelection:
    evidence: List[EvidenceItem] = field(default_factory=list)
    stats: Dict = field(default_factory=dict)


def _facet_hits(text: str, facets: Mapping[str, Sequence[str]]) -> List[str]:
    lowered = (text or "").casefold()
    return [name for name, terms in facets.items()
            if any(term.casefold() in lowered for term in terms)]


# A chronology is a list of dated events, so "is this passage still adding
# anything?" is best answered by whether it mentions a date we have not seen.
# A new document that repeats dates already in the pack contributes nothing to
# the record, however relevant it looks.
_DATE_RE = re.compile(
    r"\b(?:\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|(?:\d{1,2}\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4}"
    r"|(?:19|20)\d{2})\b",
    re.IGNORECASE,
)


def _date_signals(text: str) -> set[str]:
    return {match.group(0).casefold() for match in _DATE_RE.finditer(text or "")}


def select_pack(
    evidence: Sequence[EvidenceItem],
    *,
    facets: Mapping[str, Sequence[str]] | None = None,
    max_chars: int = MAX_PACK_CHARS,
    max_document_share: float = MAX_DOCUMENT_SHARE,
    relevance_floor: float = RELEVANCE_FLOOR,
) -> PackSelection:
    """Choose the evidence to extract from, bounded by text rather than count.

    Replaces "take the top twelve documents". That rule limited the wrong
    dimension — a `doc_id` in this corpus is a fragment, averaging ~2,000
    characters and ~14 to a file, so twelve of them was ~24,000 characters of a
    240,000,000-character corpus, about a hundredth of a percent. It also had no
    relevance threshold, so it padded a narrow topic with twelve items whether
    or not twelve were worth reading.

    Four rules, in order:

    1. Keep passages within `relevance_floor` of the best. This is what makes
       the pack adaptive: a narrow topic stops early.
    2. Guarantee every coverage facet at least one passage, admitting a
       below-floor passage where that is the only way — an uncovered facet is
       worth more than a marginally better duplicate.
    3. Never let one file exceed `max_document_share` of the budget.
    4. Fill by relevance until `max_chars`.

    Grouping is by `file_name`, not `doc_id`: the cap is meant to stop one
    *document* dominating, and doc_ids are fragments of documents.
    """
    ranked = sorted(evidence, key=lambda item: float(item.score or 0.0), reverse=True)
    stats: Dict = {
        "candidates": len(ranked), "dropped_below_floor": 0,
        "dropped_document_cap": 0, "dropped_budget": 0,
        "admitted_for_coverage": 0, "stopped_early": "",
    }
    if not ranked:
        return PackSelection([], stats)

    best = float(ranked[0].score or 0.0)
    floor = best * relevance_floor
    stats["relevance_floor"] = round(floor, 6)

    facet_map = dict(facets or {})
    per_document_cap = max(1, int(max_chars * max_document_share))

    chosen: List[EvidenceItem] = []
    chosen_ids: set[str] = set()
    used_chars = 0
    per_document: Dict[str, int] = {}
    covered: set[str] = set()

    def admit(item: EvidenceItem, *, for_coverage: bool = False) -> bool:
        nonlocal used_chars
        size = len(item.excerpt or "")
        if item.source_id in chosen_ids:
            return False
        if used_chars + size > max_chars:
            stats["dropped_budget"] += 1
            return False
        key = item.file_name or item.doc_id
        if per_document.get(key, 0) + size > per_document_cap:
            stats["dropped_document_cap"] += 1
            return False
        chosen.append(item)
        chosen_ids.add(item.source_id)
        per_document[key] = per_document.get(key, 0) + size
        used_chars += size
        covered.update(_facet_hits(item.excerpt, facet_map))
        if for_coverage:
            stats["admitted_for_coverage"] += 1
        return True

    qualifying = [item for item in ranked if float(item.score or 0.0) >= floor]
    stats["dropped_below_floor"] = len(ranked) - len(qualifying)

    # Fill in relevance order, but stop when the evidence stops saying anything
    # new. The budget is a ceiling, not a quota: reaching it is a symptom of a
    # broad topic, not a goal. Padding a pack that was already sufficient buys
    # nothing and is charged per token on every extraction batch.
    stale = 0
    dates_seen: set[str] = set()
    for item in qualifying:
        before_facets = len(covered)
        before_dates = len(dates_seen)
        if not admit(item):
            continue
        dates_seen |= _date_signals(item.excerpt)
        gained = (len(covered) > before_facets) or (len(dates_seen) > before_dates)
        stale = 0 if gained else stale + 1
        # No "all facets covered" precondition: a facet the corpus simply does
        # not contain would block this forever and the ceiling would always be
        # spent. `gained` already counts a new facet as progress, so a long
        # stale run means coverage has stopped improving too. The rescue pass
        # below still goes looking for anything still missing.
        if stale >= SATURATION_WINDOW:
            stats["stopped_early"] = "saturated"
            break
    stats["distinct_dates"] = len(dates_seen)

    # Facets still unrepresented get their best available passage, floor or not.
    for facet in facet_map:
        if facet in covered:
            continue
        for item in ranked:
            if item.source_id in chosen_ids:
                continue
            if facet in _facet_hits(item.excerpt, facet_map):
                if admit(item, for_coverage=True):
                    break

    stats["selected_passages"] = len(chosen)
    stats["selected_chars"] = used_chars
    stats["selected_documents"] = len(per_document)
    return PackSelection(chosen, stats)


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
