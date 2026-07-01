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
