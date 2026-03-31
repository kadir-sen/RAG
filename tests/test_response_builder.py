"""Unit tests for response_builder — intent mapping, citation extraction, SQL artifact."""

import pytest
from backend.services.response_builder import build_chat_response, INTENT_MAP
from backend.models.responses import ChatResponse


# ── Intent Mapping ─────────────────────────────────────────

class TestIntentMapping:
    def test_document_maps_to_answer(self):
        raw = {"query_type": "document", "answer": "test", "sources": []}
        resp = build_chat_response(raw)
        assert resp.ui_intent == "answer"

    def test_data_maps_to_sql_result(self):
        raw = {"query_type": "data", "answer": "test", "sources": []}
        resp = build_chat_response(raw)
        assert resp.ui_intent == "sql_result"

    def test_hybrid_maps_to_answer(self):
        raw = {"query_type": "hybrid", "answer": "test", "sources": []}
        resp = build_chat_response(raw)
        assert resp.ui_intent == "answer"

    def test_timeline_maps_to_doc_list(self):
        raw = {"query_type": "timeline", "answer": "test", "sources": []}
        resp = build_chat_response(raw)
        assert resp.ui_intent == "doc_list"

    def test_thread_maps_to_email_trace(self):
        raw = {"query_type": "thread", "answer": "test", "sources": []}
        resp = build_chat_response(raw)
        assert resp.ui_intent == "email_trace"

    def test_file_list_maps_to_doc_list(self):
        raw = {"query_type": "file_list", "answer": "test", "sources": []}
        resp = build_chat_response(raw)
        assert resp.ui_intent == "doc_list"

    def test_draft_maps_to_answer(self):
        raw = {"query_type": "draft", "answer": "test", "sources": []}
        resp = build_chat_response(raw)
        assert resp.ui_intent == "answer"

    def test_unknown_type_defaults_to_answer(self):
        raw = {"query_type": "unknown_type", "answer": "test", "sources": []}
        resp = build_chat_response(raw)
        assert resp.ui_intent == "answer"


# ── Citation Extraction ────────────────────────────────────

class TestCitationExtraction:
    def test_document_sources_become_citations(self):
        raw = {
            "query_type": "document",
            "answer": "The contract says...",
            "sources": [
                {
                    "file_name": "contract.pdf",
                    "page_number": 5,
                    "score": 0.92,
                    "text_snippet": "Clause 4.1 states that...",
                },
                {
                    "file_name": "agreement.pdf",
                    "page_number": 12,
                    "score": 0.78,
                    "highlight_text": "The parties agree to...",
                },
            ],
        }
        resp = build_chat_response(raw)
        assert len(resp.citations) == 2
        assert resp.citations[0].doc_name == "contract.pdf"
        assert resp.citations[0].anchor == "page_5"
        assert resp.citations[0].snippet == "Clause 4.1 states that..."
        assert resp.citations[0].score == 0.92
        assert resp.citations[1].snippet == "The parties agree to..."

    def test_notice_sources_become_related_docs(self):
        raw = {
            "query_type": "timeline",
            "answer": "Timeline of notices...",
            "sources": [
                {
                    "type": "notice",
                    "doc_id": "n_001",
                    "file_name": "notice_delay.pdf",
                    "date": "2024-01-15",
                    "subject": "Delay Notice #3",
                    "score": 0.85,
                },
            ],
        }
        resp = build_chat_response(raw)
        assert len(resp.citations) == 0
        assert len(resp.related_docs) == 1
        assert resp.related_docs[0].doc_name == "notice_delay.pdf"
        assert resp.related_docs[0].date == "2024-01-15"
        assert resp.related_docs[0].reason == "Delay Notice #3"

    def test_thread_message_sources_become_related_docs(self):
        raw = {
            "query_type": "thread",
            "answer": "Thread between A and B",
            "sources": [
                {
                    "type": "thread_message",
                    "file_name": "email_001.eml",
                    "date": "2024-02-20",
                    "sender": "alice@co.com",
                    "recipient": "bob@co.com",
                    "subject": "RE: Progress Update",
                },
            ],
        }
        resp = build_chat_response(raw)
        assert len(resp.related_docs) == 1
        assert resp.related_docs[0].reason == "RE: Progress Update"

    def test_structured_data_sources_skipped_from_citations(self):
        raw = {
            "query_type": "data",
            "answer": "Total is 500",
            "sources": [
                {
                    "type": "structured_data",
                    "table_name": "t_dpr_manpower",
                    "sql_query": "SELECT SUM(workers) FROM ...",
                    "row_count_returned": 10,
                },
            ],
            "sql": "SELECT SUM(workers) FROM t_dpr_manpower",
            "result_data": [{"total": 500}],
        }
        resp = build_chat_response(raw)
        assert len(resp.citations) == 0
        assert len(resp.related_docs) == 0

    def test_empty_sources(self):
        raw = {"query_type": "document", "answer": "No results", "sources": []}
        resp = build_chat_response(raw)
        assert resp.citations == []
        assert resp.related_docs == []

    def test_snippet_truncated_to_300_chars(self):
        long_text = "x" * 500
        raw = {
            "query_type": "document",
            "answer": "result",
            "sources": [{"file_name": "doc.pdf", "text_snippet": long_text}],
        }
        resp = build_chat_response(raw)
        assert len(resp.citations[0].snippet) == 300


# ── SQL Artifact ───────────────────────────────────────────

class TestSQLArtifact:
    def test_sql_artifact_built_from_data_query(self):
        raw = {
            "query_type": "data",
            "answer": "Total cost is $50,000",
            "sources": [
                {
                    "type": "structured_data",
                    "table_name": "t_cost_breakdown",
                    "sql_query": "SELECT SUM(amount) FROM t_cost_breakdown",
                },
            ],
            "sql": "SELECT SUM(amount) FROM t_cost_breakdown",
            "result_data": [{"sum_amount": 50000}],
        }
        resp = build_chat_response(raw)
        assert resp.sql_artifact is not None
        assert resp.sql_artifact.generated_sql == "SELECT SUM(amount) FROM t_cost_breakdown"
        assert resp.sql_artifact.tables_used == ["t_cost_breakdown"]
        assert resp.sql_artifact.row_count == 1
        assert resp.sql_artifact.preview_rows == [{"sum_amount": 50000}]

    def test_no_sql_artifact_for_document_query(self):
        raw = {
            "query_type": "document",
            "answer": "test",
            "sources": [{"file_name": "doc.pdf"}],
        }
        resp = build_chat_response(raw)
        assert resp.sql_artifact is None

    def test_preview_rows_capped_at_20(self):
        rows = [{"val": i} for i in range(50)]
        raw = {
            "query_type": "data",
            "answer": "result",
            "sources": [{"type": "structured_data", "table_name": "t"}],
            "sql": "SELECT * FROM t",
            "result_data": rows,
        }
        resp = build_chat_response(raw)
        assert len(resp.sql_artifact.preview_rows) == 20
        assert resp.sql_artifact.row_count == 50


# ── Dual-LLM Mode ─────────────────────────────────────────

class TestDualLLMMode:
    def test_dual_mode_picks_first_provider(self):
        raw = {
            "query_type": "document",
            "answers": {
                "gemini": {
                    "answer": "Gemini says...",
                    "sources": [{"file_name": "doc.pdf", "page_number": 1}],
                },
                "openai": {
                    "answer": "OpenAI says...",
                    "sources": [{"file_name": "doc.pdf", "page_number": 2}],
                },
            },
        }
        resp = build_chat_response(raw, is_dual=True)
        assert resp.assistant_text == "Gemini says..."
        assert len(resp.citations) == 1

    def test_dual_mode_empty_answers(self):
        raw = {"query_type": "document", "answers": {}}
        resp = build_chat_response(raw, is_dual=True)
        assert resp.assistant_text == ""
        assert resp.citations == []


# ── Response Contract Shape ────────────────────────────────

class TestResponseShape:
    def test_response_is_valid_pydantic_model(self):
        raw = {
            "query_type": "document",
            "answer": "Test answer",
            "sources": [
                {"file_name": "doc.pdf", "page_number": 3, "score": 0.9, "text_snippet": "hello"},
            ],
        }
        resp = build_chat_response(raw)
        assert isinstance(resp, ChatResponse)
        data = resp.model_dump()
        assert "ui_intent" in data
        assert "assistant_text" in data
        assert "citations" in data
        assert "related_docs" in data
        assert "sql_artifact" in data
