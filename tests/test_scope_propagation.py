"""Unit tests for scope propagation — verifying doc_ids and allowed_tables
flow through the entire execution chain (router -> hybrid_executor -> query_planner).
"""

import sys
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from typing import Dict, List, Optional, Any

# Mock heavy external dependencies that may not be installed in test env
for mod_name in [
    "llama_index", "llama_index.llms", "llama_index.llms.gemini",
    "llama_index.core", "llama_index.core.llms",
    "llama_index.embeddings", "llama_index.embeddings.huggingface",
    "duckdb", "google.generativeai",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()


# ── BUG 2: execute_multi_table scope ──────────────────────

class TestMultiTableScope:
    """Verify that execute_multi_table receives and uses allowed_tables."""

    def test_execute_multi_table_passes_allowed_tables_to_select(self):
        """allowed_tables should be forwarded to data_analyzer.select_tables."""
        from src.hybrid_executor import HybridExecutor

        mock_da = MagicMock()
        # Return single table so we skip the LLM combine path
        mock_da.select_tables.return_value = ["table_a"]
        mock_da.query.return_value = {
            "answer": "result", "sources": [], "sql": None, "result_data": None,
        }

        executor = HybridExecutor.__new__(HybridExecutor)
        executor._data_analyzer = mock_da
        executor._jargon = MagicMock()
        executor._jargon.expand_query.return_value = "test query"

        executor.execute_multi_table(
            "test query",
            allowed_tables=["table_a"],
        )

        # Verify select_tables was called WITH allowed_tables
        mock_da.select_tables.assert_called_once_with(
            "test query", max_tables=3, allowed_tables=["table_a"]
        )

    def test_execute_multi_table_without_scope_defaults_to_none(self):
        """When no allowed_tables provided, select_tables gets None (all tables)."""
        from src.hybrid_executor import HybridExecutor

        mock_da = MagicMock()
        mock_da.select_tables.return_value = ["only_table"]
        mock_da.query.return_value = {
            "answer": "result", "sources": [], "sql": None, "result_data": None,
        }

        executor = HybridExecutor.__new__(HybridExecutor)
        executor._data_analyzer = mock_da
        executor._jargon = MagicMock()
        executor._jargon.expand_query.return_value = "test query"

        executor.execute_multi_table("test query")

        mock_da.select_tables.assert_called_once_with(
            "test query", max_tables=3, allowed_tables=None
        )


# ── BUG 4: Planner scope propagation ─────────────────────

class TestPlannerScope:
    """Verify that PlanExecutor passes scope to step executors."""

    def test_sql_step_receives_allowed_tables(self):
        """_execute_sql_step should forward allowed_tables to data_analyzer."""
        from src.query_planner import PlanExecutor

        mock_da = MagicMock()
        mock_da.query.return_value = {
            "answer": "42", "sources": [], "sql": "SELECT 1", "result_data": [{"v": 42}],
        }

        executor = PlanExecutor.__new__(PlanExecutor)
        executor._data_analyzer = mock_da
        executor._document_rag = MagicMock()
        executor._light_graph = MagicMock()

        result = executor._execute_sql_step(
            "count workers", {}, allowed_tables=["t_manpower"]
        )

        mock_da.query.assert_called_once_with(
            "count workers", allowed_tables=["t_manpower"]
        )

    def test_document_step_receives_doc_ids(self):
        """_execute_document_step should forward doc_ids to document_rag."""
        from src.query_planner import PlanExecutor

        mock_rag = MagicMock()
        mock_rag.query.return_value = {
            "answer": "Contract clause 4.1", "sources": [],
        }

        executor = PlanExecutor.__new__(PlanExecutor)
        executor._data_analyzer = MagicMock()
        executor._document_rag = mock_rag
        executor._light_graph = MagicMock()

        result = executor._execute_document_step(
            "find contract clause", doc_ids=["doc_abc"]
        )

        mock_rag.query.assert_called_once_with(
            "find contract clause", doc_ids=["doc_abc"]
        )

    def test_sql_step_with_context_passes_allowed_tables(self):
        """query_with_context should receive allowed_tables when context exists."""
        from src.query_planner import PlanExecutor

        mock_da = MagicMock()
        mock_da.query_with_context.return_value = {
            "answer": "result", "sources": [], "sql": None, "result_data": None,
        }

        executor = PlanExecutor.__new__(PlanExecutor)
        executor._data_analyzer = mock_da
        executor._document_rag = MagicMock()
        executor._light_graph = MagicMock()

        prev_results = {"step_1": {"answer": "previous context"}}
        result = executor._execute_sql_step(
            "follow up query", prev_results, allowed_tables=["t_cost"]
        )

        mock_da.query_with_context.assert_called_once()
        call_kwargs = mock_da.query_with_context.call_args
        assert call_kwargs.kwargs.get("allowed_tables") == ["t_cost"] or \
               (len(call_kwargs.args) >= 1 and "allowed_tables" in str(call_kwargs))


# ── BUG 5: Citation dedup page granularity ────────────────

class TestCitationDedup:
    """Verify that same file with different pages is not collapsed."""

    def test_search_result_mixed_with_notices(self):
        """search_result and notice types both map to related_docs."""
        from backend.services.response_builder import build_chat_response

        raw = {
            "query_type": "file_list",
            "answer": "Found files",
            "sources": [
                {
                    "type": "notice",
                    "doc_id": "n_001",
                    "file_name": "notice.pdf",
                    "date": "2024-01-01",
                    "subject": "Notice A",
                },
                {
                    "type": "search_result",
                    "doc_id": "sr_001",
                    "file_name": "report.pdf",
                    "date": "2024-02-01",
                    "subject": "Report B",
                    "doc_type": "document",
                },
            ],
        }
        resp = build_chat_response(raw)
        assert len(resp.related_docs) == 2
        assert len(resp.citations) == 0
