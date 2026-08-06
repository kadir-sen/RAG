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


# ── Lane score normalisation (src/ai_reports._rank_normalised) ───────────
#
# The retrieval lanes return incompatible quantities — RRF (~0.03), cosine
# (0..1) and raw BM25 (unbounded). They were merged by max and then summed per
# document, so BM25-verbose documents won on magnitude alone and anything the
# lexical lane found on its own arrived as 0.0.

def test_lanes_with_wildly_different_scales_become_comparable():
    from src.ai_reports import _rank_normalised

    cosine = _rank_normalised([{"score": 0.81}, {"score": 0.62}, {"score": 0.44}])
    bm25 = _rank_normalised([{"lex_score": 14.2}, {"lex_score": 9.1}, {"lex_score": 2.0}])

    assert [row["score"] for row in cosine] == [row["score"] for row in bm25]
    assert all(0 < row["score"] <= 1 for row in cosine + bm25)
    # The lane's own number is kept for diagnostics, not for ranking.
    assert cosine[0]["lane_score"] == 0.81
    assert bm25[0]["lane_score"] == 14.2


def test_normalisation_preserves_each_lanes_own_order():
    from src.ai_reports import _rank_normalised

    rows = _rank_normalised([{"id": "a"}, {"id": "b"}, {"id": "c"}])
    assert [r["id"] for r in rows] == ["a", "b", "c"]
    assert rows[0]["score"] > rows[1]["score"] > rows[2]["score"]


def test_a_lexical_only_hit_is_never_scored_zero():
    """The live bug: no dense_score meant score None, coerced to 0.0."""
    from src.ai_reports import _rank_normalised

    rows = _rank_normalised([{"lex_score": 7.5, "score": None}])
    assert rows[0]["score"] > 0


def test_normalisation_of_an_empty_lane_is_empty():
    from src.ai_reports import _rank_normalised

    assert _rank_normalised([]) == []


def test_fused_score_reaches_the_source_instead_of_being_dropped():
    """_node_to_source returned dense_score, discarding the RRF it ranked by."""
    from src.document_rag import DocumentRAG

    node = {"file_name": "a.pdf", "page_number": 2, "doc_id": "d1",
            "text": "some evidence text", "rrf": 0.031, "lex_score": 8.0}
    source = DocumentRAG._node_to_source(object.__new__(DocumentRAG), node)

    assert source["score"] == 0.031
    assert source["rrf_score"] == 0.031
    assert source["lex_score"] == 8.0


def test_a_lexical_only_node_no_longer_yields_a_none_score():
    from src.document_rag import DocumentRAG

    node = {"file_name": "a.pdf", "page_number": 1, "doc_id": "d1",
            "text": "t", "lex_score": 5.0}          # no dense_score, no rrf
    source = DocumentRAG._node_to_source(object.__new__(DocumentRAG), node)
    assert source["score"] == 5.0
    assert source["score"] is not None


# ── Budget-bounded selection (select_pack) ───────────────────────────────

from src.evidence_pack import MAX_PACK_CHARS, PackSelection, select_pack  # noqa: E402

FACETS = {
    "delay_prolongation": ("delay", "prolongation"),
    "party_positions": ("contended", "position"),
}


def _scored(source_id, score, chars=1000, file_name="a.pdf", text=""):
    return EvidenceItem(source_id, f"doc-{source_id}", file_name, page=1,
                        excerpt=(text or "x" * chars), score=score)


def test_selection_is_bounded_by_characters_not_document_count():
    """The old rule capped count, which bounded neither cost nor batch risk."""
    # Spread across files so the budget, not the per-document share, is what bites.
    evidence = [_scored(f"s{i}", 1.0, chars=10_000, file_name=f"f{i}.pdf")
                for i in range(200)]
    pack = select_pack(evidence, facets={}, max_chars=50_000)
    assert pack.stats["selected_chars"] <= 50_000
    assert pack.stats["dropped_budget"] > 0


def test_one_document_cannot_crowd_out_the_rest():
    """A 1.8 MB inquiry report was 45% of one production pack."""
    hog = [_scored(f"h{i}", 1.0, chars=5_000, file_name="inquiry.pdf") for i in range(100)]
    others = [_scored(f"o{i}", 0.9, chars=5_000, file_name=f"letter-{i}.pdf") for i in range(20)]
    pack = select_pack(hog + others, facets={}, max_chars=100_000,
                       max_document_share=0.25)

    per_file: dict[str, int] = {}
    for item in pack.evidence:
        per_file[item.file_name] = per_file.get(item.file_name, 0) + len(item.excerpt)
    assert per_file["inquiry.pdf"] <= 25_000
    assert len(per_file) > 1, "other documents must still get in"
    assert pack.stats["dropped_document_cap"] > 0


def test_the_cap_groups_by_file_not_by_fragment():
    """doc_id is a fragment: ~14 per file in production, ~2,000 chars each.

    Capping per doc_id would cap nothing at all.
    """
    fragments = [
        EvidenceItem(f"s{i}", f"fragment-{i}", "one-file.pdf", page=i,
                     excerpt="x" * 5_000, score=1.0)
        for i in range(50)
    ]
    pack = select_pack(fragments, facets={}, max_chars=100_000,
                       max_document_share=0.25)
    assert pack.stats["selected_chars"] <= 25_000


def test_a_narrow_topic_costs_less_than_the_ceiling():
    """Adaptive: qualifying passages run out, the pack stops."""
    evidence = [_scored("top", 1.0, chars=2_000)] + [
        _scored(f"weak{i}", 0.05, chars=2_000) for i in range(300)
    ]
    pack = select_pack(evidence, facets={}, max_chars=MAX_PACK_CHARS)
    assert pack.stats["selected_passages"] == 1
    assert pack.stats["dropped_below_floor"] == 300
    assert pack.stats["selected_chars"] < MAX_PACK_CHARS / 10


def test_a_broad_topic_fills_the_budget():
    """Distinct dates throughout, so every passage is still adding a candidate
    event and there is no reason to stop early."""
    evidence = [
        _scored(f"s{i}", 1.0 - i / 1000, file_name=f"f{i % 20}.pdf",
                text=f"issued {1 + i % 28} June {2005 + i % 8} " + "x" * 2_000)
        for i in range(500)
    ]
    pack = select_pack(evidence, facets={}, max_chars=100_000)
    assert 90_000 <= pack.stats["selected_chars"] <= 100_000


def test_an_uncovered_facet_gets_a_passage_even_below_the_floor():
    evidence = [_scored(f"s{i}", 1.0, chars=500, text="contract scope wording")
                for i in range(5)]
    evidence.append(_scored("rare", 0.01, chars=500,
                            text="the contended position of the parties"))
    pack = select_pack(evidence, facets=FACETS, max_chars=100_000)

    assert "rare" in {item.source_id for item in pack.evidence}
    assert pack.stats["admitted_for_coverage"] == 1


def test_coverage_rescue_still_respects_the_budget():
    evidence = [_scored("big", 1.0, chars=9_000, text="delay and prolongation")]
    evidence.append(_scored("rare", 0.01, chars=9_000,
                            text="the contended position of the parties"))
    pack = select_pack(evidence, facets=FACETS, max_chars=10_000)
    assert pack.stats["selected_chars"] <= 10_000


def test_empty_evidence_selects_nothing_without_error():
    pack = select_pack([], facets=FACETS)
    assert isinstance(pack, PackSelection)
    assert pack.evidence == []
    assert pack.stats["candidates"] == 0


def test_a_passage_is_never_selected_twice():
    duplicate = _scored("same", 1.0, chars=100, text="delay")
    pack = select_pack([duplicate, duplicate], facets=FACETS, max_chars=10_000)
    assert len(pack.evidence) == 1


def test_v3_carries_document_scores_onto_its_passages():
    """Without this every v3 passage arrives at 0.0 and cannot be ranked.

    v3 picks documents well — length-normalised BM25, roles, a relevance
    threshold — then read them whole with no score, so the budget had nothing
    to order by and would keep whichever passages happened to come first.
    """
    from src import chronology_v3

    class _Con:
        def execute(self, *_a):
            return self

        def fetchall(self):
            return [("d1", "a.pdf", 1, "strong evidence"),
                    ("d2", "b.pdf", 1, "weaker evidence")]

    class _Store:
        def connection(self):
            return _Con()

    import src.chunk_store as chunk_store
    original_store = chunk_store.get_chunk_store
    original_index = chronology_v3.get_document_index
    chunk_store.get_chunk_store = lambda: _Store()
    chronology_v3.get_document_index = lambda: type(
        "I", (), {"list_project": lambda _s, _p: []})()
    try:
        evidence = chronology_v3.evidence_from_documents(
            "p", ["d1", "d2"], {"d1": 9.5, "d2": 1.0},
        )
    finally:
        chunk_store.get_chunk_store = original_store
        chronology_v3.get_document_index = original_index

    by_doc = {item.doc_id: item.score for item in evidence}
    assert by_doc == {"d1": 9.5, "d2": 1.0}


# ── Saturation: the budget is a ceiling, not a target ────────────────────

def test_a_saturated_pack_stops_well_below_the_ceiling():
    """Once every facet is covered and nothing new arrives, stop paying.

    Filling 240,000 characters when 70,000 already answered the topic buys
    nothing and is charged per token on every extraction batch.
    """
    # Ten documents cover both facets, then 400 more passages repeat one of them.
    useful = [
        _scored(f"u{i}", 1.0, chars=2_000, file_name=f"doc-{i}.pdf",
                text="delay and prolongation; the contended position of the parties")
        for i in range(10)
    ]
    padding = [
        _scored(f"p{i}", 0.9, chars=2_000, file_name="doc-0.pdf", text="delay again")
        for i in range(400)
    ]
    pack = select_pack(useful + padding, facets=FACETS, max_chars=MAX_PACK_CHARS)

    assert pack.stats["stopped_early"] == "saturated"
    assert pack.stats["selected_chars"] < MAX_PACK_CHARS / 2
    assert set(FACETS) <= set(
        f for item in pack.evidence
        for f, terms in FACETS.items()
        if any(t in item.excerpt for t in terms)
    )


def test_a_genuinely_broad_topic_is_not_cut_short_by_saturation():
    """Each passage carries a date not yet in the pack, so it is still earning
    its place — a six-year contract history looks like this."""
    body = "delay and prolongation; the contended position of the parties "
    evidence = [
        _scored(f"s{i}", 1.0 - i / 1000, file_name=f"doc-{i}.pdf",
                text=f"{body} on {1 + i % 28} March {2005 + i % 7} " + "y" * 2_000)
        for i in range(300)
    ]
    pack = select_pack(evidence, facets=FACETS, max_chars=100_000)
    assert pack.stats["stopped_early"] == ""
    assert pack.stats["selected_chars"] >= 90_000
    assert pack.stats["distinct_dates"] > 20


def test_a_facet_the_corpus_lacks_does_not_force_the_budget_to_be_spent():
    """Waiting for a facet nothing can cover would spend the ceiling every time.

    On the real corpus `contradictions_missing` is often uncoverable, and an
    "all facets covered" precondition meant the pack always ran to 240,000
    characters no matter how repetitive the evidence was.
    """
    repetitive = [
        _scored(f"s{i}", 1.0, file_name=f"doc-{i}.pdf",
                text="delay on 3 May 2006; the contended position " + "z" * 1_000)
        for i in range(400)
    ]
    pack = select_pack(repetitive, facets=FACETS, max_chars=MAX_PACK_CHARS)

    assert pack.stats["stopped_early"] == "saturated"
    assert pack.stats["selected_chars"] < MAX_PACK_CHARS / 3


def test_an_explicit_selection_shares_the_budget_across_its_documents():
    """Removing the twenty-document cap must not let one document eat the pack."""
    evidence = []
    for doc in range(40):
        evidence += [
            EvidenceItem(f"s{doc}-{i}", f"d{doc}-{i}", f"doc-{doc}.pdf", page=i,
                         excerpt="x" * 5_000, score=0.0)
            for i in range(20)
        ]
    pack = select_pack(evidence, facets={}, max_chars=200_000,
                       max_document_share=1.0 / 40, relevance_floor=0.0)

    per_file: dict[str, int] = {}
    for item in pack.evidence:
        per_file[item.file_name] = per_file.get(item.file_name, 0) + len(item.excerpt)
    assert pack.stats["selected_chars"] <= 200_000
    assert len(per_file) > 20, "every chosen document should be represented"
    assert max(per_file.values()) <= 200_000 / 40 + 5_000
