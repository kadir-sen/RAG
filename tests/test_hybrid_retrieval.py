"""Faz 1 — hybrid retrieval birim testleri (network/LLM gerektirmez).

  * chunk_store: yaz/dedupe/sil
  * lexical_index.search_chunks: DuckDB BM25 sıralaması (+ LIKE fallback yolu)
  * lexical_index.rrf_fuse: saf RRF füzyonu, doc-keyword boost tiebreaker
"""
import pytest

from src.chunk_store import get_chunk_store, _chunk_id
from src.lexical_index import get_lexical_index, rrf_fuse


@pytest.fixture
def clean_store():
    cs = get_chunk_store()
    for f in ("a.pdf", "b.pdf", "c.pdf"):
        cs.delete_by_file(f)
    yield cs
    for f in ("a.pdf", "b.pdf", "c.pdf"):
        cs.delete_by_file(f)


# ── chunk_store ─────────────────────────────────────────────────────────────
class TestChunkStore:
    def test_add_dedupe_delete(self, clean_store):
        cs = clean_store
        n = cs.add_chunks([
            {"doc_id": "d1", "file_name": "a.pdf", "page_number": 1, "text": "alpha text one"},
            {"doc_id": "d1", "file_name": "a.pdf", "page_number": 2, "text": "beta text two"},
            {"doc_id": "d1", "file_name": "a.pdf", "page_number": 1, "text": "alpha text one"},  # dup
        ])
        assert n == 2  # duplicate skipped
        assert cs.count() == 2
        assert cs.delete_by_file("a.pdf") == 2
        assert cs.count() == 0

    def test_empty_text_skipped(self, clean_store):
        cs = clean_store
        assert cs.add_chunks([{"doc_id": "d1", "file_name": "a.pdf", "page_number": 1, "text": "   "}]) == 0

    def test_chunk_id_stable(self):
        assert _chunk_id("a.pdf", 1, "x") == _chunk_id("a.pdf", 1, "x")
        assert _chunk_id("a.pdf", 1, "x") != _chunk_id("a.pdf", 2, "x")


# ── lexical BM25 search ─────────────────────────────────────────────────────
class TestLexicalSearch:
    def test_bm25_ranks_relevant_chunk_first(self, clean_store):
        cs = clean_store
        cs.add_chunks([
            {"doc_id": "d1", "file_name": "a.pdf", "page_number": 1,
             "text": "Extension of time EOT delay notice for Block A concrete works"},
            {"doc_id": "d1", "file_name": "a.pdf", "page_number": 2,
             "text": "Liquidated damages clause 12.3 payment terms and conditions"},
            {"doc_id": "d2", "file_name": "b.pdf", "page_number": 1,
             "text": "Crane equipment utilization hours by block manpower"},
        ])
        res = get_lexical_index().search_chunks("extension of time delay Block A", top_k=5)
        assert res, "lexical search returned nothing"
        assert res[0]["file_name"] == "a.pdf" and res[0]["page_number"] == 1

    def test_empty_query_returns_empty(self, clean_store):
        assert get_lexical_index().search_chunks("   ", top_k=5) == []


# ── RRF fusion (pure) ───────────────────────────────────────────────────────
class TestRRFFusion:
    def _dense(self):
        return [
            {"key": "a.pdf::1", "doc_id": "d1", "file_name": "a.pdf",
             "file_path": "/a.pdf", "page_number": 1, "total_pages": 2, "text": "dense top"},
            {"key": "a.pdf::2", "doc_id": "d1", "file_name": "a.pdf",
             "page_number": 2, "text": "dense second"},
        ]

    def _lexical(self):
        return [
            {"key": "b.pdf::1", "doc_id": "d2", "file_name": "b.pdf", "page_number": 1, "text": "lex only"},
            {"key": "a.pdf::1", "doc_id": "d1", "file_name": "a.pdf", "page_number": 1, "text": "same lex"},
        ]

    def test_dual_lane_chunk_ranked_first(self):
        out = rrf_fuse(self._dense(), self._lexical(), {}, rrf_k=60)
        assert out[0]["key"] == "a.pdf::1"  # appears in both lanes → highest

    def test_metadata_merged_across_lanes(self):
        out = rrf_fuse(self._dense(), self._lexical(), {}, rrf_k=60)
        top = next(n for n in out if n["key"] == "a.pdf::1")
        assert top["file_path"] == "/a.pdf"  # merged from dense lane
        assert top["total_pages"] == 2

    def test_doc_boost_is_gentle_tiebreaker_not_override(self):
        # Even a full doc_boost on d2 must NOT lift a single-lane chunk above a
        # dual-lane chunk.
        out = rrf_fuse(self._dense(), self._lexical(), {"d2": 1.0}, rrf_k=60)
        assert out[0]["key"] == "a.pdf::1"

    def test_doc_boost_breaks_ties_between_equal_chunks(self):
        dense = [{"key": "x::1", "doc_id": "dx", "file_name": "x", "page_number": 1, "text": "x"}]
        lexical = [{"key": "y::1", "doc_id": "dy", "file_name": "y", "page_number": 1, "text": "y"}]
        # Both at rank 0 in their single lane → equal RRF; boost on dy wins.
        out = rrf_fuse(dense, lexical, {"dy": 1.0}, rrf_k=60)
        assert out[0]["key"] == "y::1"

    def test_empty_inputs(self):
        assert rrf_fuse([], [], {}) == []
