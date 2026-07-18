"""Sprint B — deterministic reranker.

Vector order alone mis-ranks evidence. These tests lock in the signals the
reranker adds on top of the fused score: term/phrase overlap fixes a wrong top
result, entity and date-range matches promote the right page, wrong
project/doc-type are penalized, MMR breaks up near-duplicates, and every failure
mode degrades safely to the fused order (retrieval never fails because rerank
did).
"""

import pytest

from src.rag import rerank_candidates, to_evidence_packet
from src.rag.reranker import _norm_date, _in_range


@pytest.fixture(autouse=True)
def _no_real_cross_encoder(monkeypatch):
    """Keep every reranker test offline — never let a test download/load a real
    cross-encoder model. The CE-specific tests re-patch this with a stub."""
    import src.rag.reranker as rr
    monkeypatch.setattr(rr, "_get_cross_encoder", lambda: None)


def _c(key, text, **kw):
    d = {"key": key, "file_name": kw.pop("file_name", f"{key}.pdf"),
         "doc_id": kw.pop("doc_id", key), "page_number": kw.pop("page", 1),
         "text": text}
    d.update(kw)
    return d


class TestRelevanceCorrection:
    def test_reranker_fixes_wrong_vector_order(self):
        # Vector put the off-topic page first (higher dense_score); the on-topic
        # page must win after reranking on term/phrase overlap.
        cands = [
            _c("a", "General site safety induction and PPE policy.",
               dense_score=0.90),
            _c("b", "The concrete pour for block B was delayed by the crane "
                    "breakdown on 2024-03-01.", dense_score=0.55),
        ]
        out = rerank_candidates("crane breakdown delayed concrete pour block B",
                                cands, top_k=2)
        assert out[0]["key"] == "b"
        assert out[0]["rerank_score"] > out[1]["rerank_score"]

    def test_exact_phrase_promoted(self):
        cands = [
            _c("a", "Discussion of scheduling and resources in general terms.",
               dense_score=0.7),
            _c("b", "Notice: extension of time granted for the foundation works.",
               dense_score=0.7),
        ]
        out = rerank_candidates('"extension of time"', cands, top_k=2)
        assert out[0]["key"] == "b"
        assert any("phrase" in w for w in out[0]["why_selected"])


class TestFilters:
    def test_entity_match_promoted(self):
        cands = [
            _c("a", "Weekly progress across all zones was nominal.",
               dense_score=0.8),
            _c("b", "Subcontractor Acme Piping raised an RFI on the pile caps.",
               dense_score=0.6),
        ]
        out = rerank_candidates("RFI on pile caps", cands,
                                entities=["Acme Piping"], top_k=2)
        assert out[0]["key"] == "b"
        assert any("entity" in w for w in out[0]["why_selected"])

    def test_date_in_range_promoted(self):
        cands = [
            _c("a", "Meeting held on 2023-01-05 about mobilisation.",
               dense_score=0.8),
            _c("b", "Delay event recorded on 2024-03-15 near the deadline.",
               dense_score=0.7),
        ]
        out = rerank_candidates("delay event", cands,
                                date_range=("2024-03-01", "2024-03-31"), top_k=2)
        assert out[0]["key"] == "b"
        assert any("date" in w for w in out[0]["why_selected"])

    def test_wrong_project_penalized(self):
        cands = [
            _c("a", "Delay to the tower crane erection.", dense_score=0.85,
               project="marina_towers"),
            _c("b", "Delay to the tower crane erection.", dense_score=0.70,
               project="downtown_mall"),
        ]
        out = rerank_candidates("crane delay", cands, project="downtown_mall",
                                top_k=2)
        assert out[0]["key"] == "b"   # same text, but 'a' is the wrong project

    def test_wrong_doctype_penalized(self):
        cands = [
            _c("a", "extension of time and delay", dense_score=0.85,
               doc_type="invoice"),
            _c("b", "extension of time and delay", dense_score=0.70,
               doc_type="notice"),
        ]
        out = rerank_candidates("extension of time delay", cands,
                                doc_types=["notice", "letter"], top_k=2)
        assert out[0]["key"] == "b"


class TestMMRDiversity:
    def test_near_duplicates_diversified(self):
        # Equal relevance (same score + query term) so MMR — not relevance —
        # decides slot 2: the exact-duplicate b is redundant with a, the distinct
        # c is not, so c must take the second slot.
        dup = "Delay to the concrete pour caused by the crane breakdown."
        cands = [
            _c("a", dup, dense_score=0.80),
            _c("b", dup, dense_score=0.80),
            _c("c", "Delay to the electrical rough-in from a late material "
                    "delivery.", dense_score=0.80),
        ]
        out = rerank_candidates("delay", cands, top_k=2)
        keys = [o["key"] for o in out]
        assert "c" in keys and "b" not in keys


class TestSafety:
    def test_empty_returns_empty(self):
        assert rerank_candidates("x", []) == []

    def test_top_k_respected(self):
        cands = [_c(str(i), f"text about topic {i}") for i in range(10)]
        out = rerank_candidates("topic", cands, top_k=3)
        assert len(out) == 3

    def test_annotations_present(self):
        out = rerank_candidates("crane delay", [_c("a", "crane delay event")],
                                top_k=1)
        assert "rerank_score" in out[0] and "why_selected" in out[0]

    def test_input_not_mutated(self):
        c = _c("a", "crane delay")
        rerank_candidates("crane", [c], top_k=1)
        assert "rerank_score" not in c   # returned dicts are copies


class TestEvidencePacket:
    def test_packet_fields(self):
        out = rerank_candidates("crane delay on block B", [
            _c("a", "Crane delay on block B recorded.", file_name="L1.pdf",
               page=3, dense_score=0.8, doc_date="2024-03-01")], top_k=1)
        pkt = to_evidence_packet(out[0])
        assert pkt.document_name == "L1.pdf"
        assert pkt.page == 3
        assert pkt.citation == "L1.pdf, p.3"
        assert pkt.date == "2024-03-01"
        assert pkt.rerank_score == out[0]["rerank_score"]
        assert pkt.why_selected == out[0]["why_selected"]


class TestCrossEncoderBlend:
    """Tier-2 cross-encoder blends on top of Tier-1 when enabled; it is offline-
    stubbed here (no model download) and must degrade to Tier-1 when absent."""

    def _stub(self, scores):
        class _M:
            def score(self, query, docs):
                return [scores.get(d[:12], 0.0) for d in docs]
        return _M()

    def test_cross_encoder_reorders_when_enabled(self, monkeypatch):
        import src.rag.reranker as rr
        monkeypatch.setattr("src.config.ENABLE_CROSS_ENCODER", True, raising=False)
        # CE strongly prefers 'b' though Tier-1 base is equal
        monkeypatch.setattr(rr, "_get_cross_encoder",
                            lambda: self._stub({"about topic": 0.1,
                                                "the answer ": 0.9}))
        cands = [_c("a", "about topic generalities", dense_score=0.8),
                 _c("b", "the answer to the exact question", dense_score=0.8)]
        out = rr.rerank_candidates("question", cands, top_k=2, strategy="hybrid")
        assert out[0]["key"] == "b"
        assert any("cross-encoder" in w for w in out[0]["why_selected"])

    def test_absent_model_degrades_to_tier1(self, monkeypatch):
        import src.rag.reranker as rr
        monkeypatch.setattr("src.config.ENABLE_CROSS_ENCODER", True, raising=False)
        monkeypatch.setattr(rr, "_get_cross_encoder", lambda: None)
        cands = [_c("a", "crane delay event on block B", dense_score=0.6),
                 _c("b", "unrelated safety induction", dense_score=0.9)]
        # no CE → Tier-1 still ranks the on-topic 'a' first via coverage
        out = rr.rerank_candidates("crane delay block B", cands, top_k=2)
        assert out[0]["key"] == "a"


class TestDateHelpers:
    @pytest.mark.parametrize("raw,expected", [
        ("2024-03-01", "2024-03-01"),
        ("1/3/2024", "2024-03-01"),
        ("2024-3", "2024-03-01"),
        ("garbage", None),
    ])
    def test_norm_date(self, raw, expected):
        assert _norm_date(raw) == expected

    def test_in_range(self):
        assert _in_range(["2024-03-15"], ("2024-03-01", "2024-03-31")) is True
        assert _in_range(["2023-01-01"], ("2024-03-01", "2024-03-31")) is False
        assert _in_range([], ("2024-03-01", "2024-03-31")) is False
