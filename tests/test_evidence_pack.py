from __future__ import annotations

from src.evidence_model import EvidenceItem
from src.evidence_pack import THIN_RECORD_EVENTS, assess_pack, describe_pack


def _items(count: int, *, chars: int = 100, file_name: str = "a.pdf",
           doc_prefix: str = "d") -> list[EvidenceItem]:
    return [
        EvidenceItem(f"s{i}", f"{doc_prefix}{i}", file_name, page=i, excerpt="x" * chars)
        for i in range(count)
    ]


FULL_COVERAGE = {"contractual_framework": 3, "delay_prolongation": 2}


def test_describe_pack_separates_documents_from_fragments():
    """One file averages ~14 doc_ids in production; the pack must say both.

    Reporting only a document count is how "twelve documents" hid the fact that
    twelve fragments of ~2,000 characters had been selected.
    """
    evidence = _items(12, file_name="same.pdf")          # 12 doc_ids, 1 file
    pack = describe_pack(evidence)
    assert pack["documents"] == 1
    assert pack["fragments"] == 12
    assert pack["passages"] == 12
    assert pack["chars"] == 12 * 100


def test_a_thin_record_is_reported_as_partial():
    assessment = assess_pack(
        evidence=_items(3), event_count=3, coverage=FULL_COVERAGE,
    )
    assert assessment.status == "partial"
    assert "thin_record" in assessment.reasons
    assert assessment.pack["events"] == 3


def test_a_full_record_with_covered_facets_is_complete():
    assessment = assess_pack(
        evidence=_items(40), event_count=THIN_RECORD_EVENTS, coverage=FULL_COVERAGE,
    )
    assert assessment.status == "complete"
    assert assessment.reasons == []


def test_dropped_extraction_batches_prevent_a_complete_claim():
    """The production failure this exists to stop: batches fail, report says fine."""
    assessment = assess_pack(
        evidence=_items(40), event_count=12, coverage=FULL_COVERAGE,
        extraction_stats={"batches_total": 6, "batches_failed": 5,
                          "passages_dropped": 120,
                          "batch_errors": [{"step": "extract:2", "reason": "boom"}]},
    )
    assert assessment.status == "partial"
    assert "evidence_extraction_incomplete" in assessment.reasons
    assert assessment.pack["batches_failed"] == 5
    assert assessment.pack["passages_dropped"] == 120


def test_an_uncovered_facet_prevents_a_complete_claim():
    assessment = assess_pack(
        evidence=_items(40), event_count=12,
        coverage={"contractual_framework": 4, "party_positions": 0},
    )
    assert assessment.status == "partial"
    assert "uncovered_facets" in assessment.reasons


def test_reasons_accumulate_rather_than_shadow_each_other():
    assessment = assess_pack(
        evidence=_items(2), event_count=1,
        coverage={"party_positions": 0},
        extraction_stats={"batches_failed": 1},
    )
    assert set(assessment.reasons) == {
        "uncovered_facets", "evidence_extraction_incomplete", "thin_record",
    }
