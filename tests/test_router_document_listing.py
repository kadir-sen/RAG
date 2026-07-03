"""Tests for the deterministic document-LISTING route.

"X related documents" / "documents related to Y" / "X ile ilgili dokümanlar"
must classify as FILE_LIST (→ ui_intent doc_list → chronological table) BEFORE
the LLM classifier, and `_handle_file_list_query` must extract the topic and
return a one-line summary + `search_result` sources (which the frontend renders
as DocumentAnalysisTable). Genuine content questions must NOT be captured.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.router import QueryRouter, QueryType  # noqa: E402


def _make_router() -> QueryRouter:
    router = QueryRouter.__new__(QueryRouter)
    router.document_rag = None
    router.data_analyzer = None
    router._jargon = None
    router._hybrid_executor = None
    router._schema_alias_cache = {}
    return router


class TestListingClassification:
    def test_x_related_documents_is_file_list(self):
        d = _make_router()._classify_document_listing("fasta related documents")
        assert d is not None
        assert d.query_type == QueryType.FILE_LIST

    def test_documents_related_to_x_is_file_list(self):
        d = _make_router()._classify_document_listing(
            "documents related to the fire alarm system"
        )
        assert d is not None and d.query_type == QueryType.FILE_LIST

    def test_list_documents_about_is_file_list(self):
        d = _make_router()._classify_document_listing("show me the files about payment")
        assert d is not None and d.query_type == QueryType.FILE_LIST

    def test_turkish_listing_is_file_list(self):
        d = _make_router()._classify_document_listing("sözleşme dokümanları")
        assert d is not None and d.query_type == QueryType.FILE_LIST

    def test_content_question_not_captured(self):
        # A synthesis/content question must fall through to the LLM (returns None).
        assert _make_router()._classify_document_listing(
            "what do the documents say about liquidated damages"
        ) is None

    def test_data_question_not_captured(self):
        assert _make_router()._classify_document_listing(
            "how many steel fixers were on block a in january"
        ) is None


class TestTopicExtractionAndSummary:
    def _stubbed_router(self, captured):
        router = _make_router()

        def fake_search(topic, limit=20):
            captured["topic"] = topic
            return [
                {
                    "doc_id": "d1", "file_name": "CONTRACT.pdf",
                    "file_path": "/tmp/CONTRACT.pdf", "file_type": "document",
                    "extension": ".pdf", "date": "2016-08-07", "sender": "",
                    "recipient": "", "subject": "", "description": "",
                    "doc_type": "contract",
                },
                {
                    "doc_id": "d2", "file_name": "USB.pdf",
                    "file_path": "/tmp/USB.pdf", "file_type": "document",
                    "extension": ".pdf", "date": "", "sender": "",
                    "recipient": "", "subject": "", "description": "", "doc_type": "",
                },
            ]

        router._unified_document_search = fake_search
        return router

    def test_related_documents_extracts_topic_and_summarizes(self):
        captured: dict = {}
        result = self._stubbed_router(captured)._handle_file_list_query(
            "Fasta related documents"
        )
        # topic extracted from "X related documents" (handler lowercases the query,
        # consistent with every other topic pattern in _handle_file_list_query)
        assert captured["topic"] == "fasta"
        assert result["query_type"] == QueryType.FILE_LIST.value
        # one-line summary, no verbose numbered per-file lines
        assert "Found 2 document(s) related to 'fasta'." in result["answer"]
        assert "\n1. " not in result["answer"]
        # sources tagged for related_docs mapping, with dates preserved
        assert len(result["sources"]) == 2
        assert all(s["type"] == "search_result" for s in result["sources"])
        assert result["sources"][0]["date"] == "2016-08-07"
        assert result["sources"][1]["date"] == ""

    def test_documents_related_to_extracts_trailing_topic(self):
        captured: dict = {}
        self._stubbed_router(captured)._handle_file_list_query(
            "documents related to fire alarm"
        )
        assert captured["topic"] == "fire alarm"


def _augmented(question: str) -> str:
    """Build a context-augmented query exactly like chat_orchestrator does."""
    context = (
        "<CONVERSATION_HISTORY>\n"
        "User: show me emails from John Smith\n"
        "Assistant: [THREAD] Here are the emails from John Smith. "
        "You can reply to the consultant about the delay.\n"
        "</CONVERSATION_HISTORY>"
    )
    return f"{context}\n\nCurrent question: {question}"


class _JargonStub:
    def expand_query(self, q):
        return q


class TestCurrentQuestionHelper:
    def test_no_marker_returns_unchanged(self):
        assert QueryRouter._current_question("fasta related documents") == (
            "fasta related documents"
        )

    def test_strips_context_before_last_marker(self):
        blob = "history... Current question: first\n\nCurrent question: fasta docs"
        assert QueryRouter._current_question(blob) == "fasta docs"

    def test_case_insensitive_marker(self):
        assert QueryRouter._current_question(
            "ctx current question: fasta"
        ) == "fasta"

    def test_removes_history_tags(self):
        blob = "<CONVERSATION_HISTORY>x</CONVERSATION_HISTORY>\n\nCurrent question: y"
        assert QueryRouter._current_question(blob) == "y"


class TestAugmentedQueryRouting:
    """The orchestrator passes '{context}\\n\\nCurrent question: {q}' to the
    router. Deterministic classification and topic extraction must see only
    the current question — prior turns must not hijack the route."""

    def _classify_router(self) -> QueryRouter:
        router = _make_router()
        router._jargon = _JargonStub()
        return router

    def test_listing_wins_over_thread_phrases_in_history(self):
        # History contains "emails from" / "reply to" — without stripping,
        # _classify_thread_draft hijacks this to THREAD/DRAFT.
        d = self._classify_router().classify_query(
            _augmented("fasta related documents")
        )
        assert d.query_type == QueryType.FILE_LIST

    def test_bare_query_still_classifies_file_list(self):
        d = self._classify_router().classify_query("fasta related documents")
        assert d.query_type == QueryType.FILE_LIST

    def test_turkish_listing_on_augmented_query(self):
        d = self._classify_router().classify_query(_augmented("fasta dokümanları"))
        assert d.query_type == QueryType.FILE_LIST

    def test_topic_extraction_ignores_context(self):
        captured: dict = {}
        router = TestTopicExtractionAndSummary()._stubbed_router(captured)
        result = router._handle_file_list_query(_augmented("Fasta related documents"))
        assert captured["topic"] == "fasta"
        assert result["query_type"] == QueryType.FILE_LIST.value
        assert all(s["type"] == "search_result" for s in result["sources"])

    def test_turkish_topic_extraction_on_augmented_query(self):
        captured: dict = {}
        router = TestTopicExtractionAndSummary()._stubbed_router(captured)
        router._handle_file_list_query(_augmented("fasta dokümanları"))
        assert captured["topic"] == "fasta"

    def test_content_question_still_not_captured_multiturn(self):
        r = _make_router()
        current = r._current_question(
            _augmented("what do the documents say about liquidated damages")
        )
        assert r._classify_document_listing(current.lower()) is None


class TestBulkCorpusChunkSearch:
    """For a bulk-corpus user (corpus_var set, e.g. 'edinburgh'), the unified
    document search must query the chunk mirror — the demo-oriented sources
    don't index that corpus, and only mirror file_names survive the
    orchestrator's per-corpus filter. Demo users (no corpus) must never see
    chunk-store results."""

    def _router_with_chunk_store(self, monkeypatch):
        import duckdb
        from src import chunk_store as cs

        con = duckdb.connect(":memory:")
        con.execute(
            "CREATE TABLE chunks (chunk_id VARCHAR, doc_id VARCHAR, "
            "file_name VARCHAR, page_number INTEGER, text VARCHAR)"
        )
        con.execute(
            "INSERT INTO chunks VALUES "
            "('c1','doc_fasta','FASTA_SPEC.pdf',1,'fasta installation notes'),"
            "('c2','doc_fasta','FASTA_SPEC.pdf',2,'more fasta details'),"
            "('c3','doc_tram','TRAM_REPORT.pdf',1,'tram budget overview')"
        )

        class _StubStore:
            def connection(self):
                return con

        monkeypatch.setattr(cs, "get_chunk_store", lambda: _StubStore())

        router = _make_router()
        # No demo sources in this test: registry lookup returns None.
        class _EmptyRegistry:
            def get(self, _):
                return None
            def search_by_name(self, _):
                return []
        import src.document_registry as dr
        monkeypatch.setattr(dr, "get_document_registry", lambda: _EmptyRegistry())
        return router

    def test_chunk_hits_for_bulk_corpus_user(self, monkeypatch):
        from src.document_rag import corpus_var
        router = self._router_with_chunk_store(monkeypatch)
        token = corpus_var.set("edinburgh")
        try:
            results = router._unified_document_search("fasta")
        finally:
            corpus_var.reset(token)
        names = [r["file_name"] for r in results]
        assert "FASTA_SPEC.pdf" in names
        hit = next(r for r in results if r["file_name"] == "FASTA_SPEC.pdf")
        assert hit["source"] == "chunk_store"
        assert hit["doc_id"] == "doc_fasta"

    def test_no_chunk_hits_for_demo_user(self, monkeypatch):
        from src.document_rag import corpus_var
        router = self._router_with_chunk_store(monkeypatch)
        token = corpus_var.set("")
        try:
            results = router._unified_document_search("fasta")
        finally:
            corpus_var.reset(token)
        assert all(r.get("source") != "chunk_store" for r in results)
