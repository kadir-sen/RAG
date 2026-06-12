"""Regression tests for the v2 live-test findings fixes.

Covers the pure, fast-to-test units behind the four highest-impact changes:
  * SQL routing — strong structured-data signal detection (router)
  * SQL completeness — spurious LIMIT stripping on aggregation queries
  * Corrupt date display — trailing-letter cleanup on ISO dates
  * Grammar + citation hygiene in the response builder
"""

import pytest

from src.router import _has_strong_data_signal
from src.data_analyzer_sql import DataAnalyzerSQL
from backend.services.response_builder import (
    clean_corrupted_date_string,
    _clean_answer_text,
    build_chat_response,
)


# ── Routing: strong structured-data signal ────────────────────────────────
class TestStrongDataSignal:
    @pytest.mark.parametrize("q", [
        "what is the total number of workers by trade? show me the breakdown as a table",
        "from the spreadsheet data, give me the total manpower count grouped by trade for all weeks",
        "using the manpower production log spreadsheets, what is the total count of workers per trade across all blocks and all weeks?",
    ])
    def test_data_queries_detected(self, q):
        # These three queries returned "Empty Response" in testing because the
        # generic "show me the" phrasing misrouted them to DOCUMENT.
        assert _has_strong_data_signal(q) is True

    @pytest.mark.parametrize("q", [
        "what does the contract say about liability",
        "summarize the inspection letter",
        "explain the delay notice from the engineer",
        "tell me about the project scope",
    ])
    def test_document_queries_not_captured(self, q):
        assert _has_strong_data_signal(q) is False


# ── SQL: strip spurious LIMIT from aggregation queries ─────────────────────
class TestStripUnwantedLimit:
    def test_strips_limit_on_groupby_without_subset_intent(self):
        sql = ('SELECT "Job Description", SUM("Number of Workers") AS total_workers '
               'FROM manpower GROUP BY "Job Description" ORDER BY total_workers DESC LIMIT 5')
        out = DataAnalyzerSQL._strip_unwanted_limit(sql, "how many workers by trade?")
        assert "LIMIT" not in out.upper()
        assert "GROUP BY" in out.upper()

    def test_keeps_limit_when_user_asks_top_n(self):
        sql = ('SELECT "Block", SUM("Number of Workers") AS w FROM m '
               'GROUP BY "Block" ORDER BY w DESC LIMIT 5')
        out = DataAnalyzerSQL._strip_unwanted_limit(sql, "top 5 blocks by workers")
        assert "LIMIT 5" in out.upper()

    def test_keeps_limit_for_peak_query(self):
        sql = ('SELECT "Date", SUM("Hours") AS h FROM e '
               'GROUP BY "Date" ORDER BY h DESC LIMIT 1')
        out = DataAnalyzerSQL._strip_unwanted_limit(sql, "peak crane usage day")
        assert "LIMIT 1" in out.upper()

    def test_does_not_touch_non_aggregate_query(self):
        sql = 'SELECT * FROM t LIMIT 10'
        out = DataAnalyzerSQL._strip_unwanted_limit(sql, "show first rows")
        assert out == sql


# ── Corrupt date cleanup ───────────────────────────────────────────────────
class TestCleanCorruptedDate:
    def test_strips_trailing_letter(self):
        assert clean_corrupted_date_string("2027-03-23T00:00:00A") == "2027-03-23T00:00:00"

    def test_strips_trailing_letter_date_only(self):
        assert clean_corrupted_date_string("2016-05-01B") == "2016-05-01"

    def test_valid_iso_unchanged(self):
        assert clean_corrupted_date_string("2026-05-14T09:12:00") == "2026-05-14T09:12:00"

    def test_non_date_unchanged(self):
        assert clean_corrupted_date_string("Block A") == "Block A"


# ── Grammar + citation hygiene ─────────────────────────────────────────────
class TestAnswerHygiene:
    def test_double_negative_collapsed(self):
        assert _clean_answer_text("The context does not not contain that.") == \
            "The context does not contain that."

    def test_plain_not_not_collapsed(self):
        assert _clean_answer_text("It is not not here") == "It is not here"

    def test_empty_document_answer_drops_email_citations(self):
        raw = {
            "query_type": "document",
            "answer": "",
            "sources": [{
                "doc_id": "eml-1", "file_name": "unrelated_access_card.eml",
                "page_number": 1, "text_snippet": "access card request",
            }],
        }
        resp = build_chat_response(raw)
        assert resp.citations == []
        assert resp.related_docs == []
