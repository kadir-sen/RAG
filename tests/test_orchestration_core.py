"""Orchestration core: routing matrix, blocks contract, retry, chart guard."""

from unittest.mock import patch

import pytest

from backend.models.blocks import validate_blocks
from src.orchestration import match_composite
from src.orchestration.retry import execute_step
from src.orchestration.schemas import RetryPolicy
from src.orchestration.viz import (bar_chart_from_table, chart_guard,
                                   line_chart_from_series,
                                   line_chart_from_table)


class TestCompositeRoutingMatrix:
    @pytest.mark.parametrize("q,expected", [
        ("Show milestone movements as a chart", "composite.milestone_shift_visual"),
        ("chart how the completion dates slipped", "composite.milestone_shift_visual"),
        ("Create a bar chart of manpower by trade for June 2024", "composite.sql_metric_chart"),
        ("plot equipment utilization by block", "composite.sql_metric_chart"),
        ("Compare baseline and current programme and explain the key shifts",
         "composite.programme_compare"),
        ("Prepare the 6.1 chronology for delayed blockwork as an html report section",
         "composite.chronology_html"),
        ("Make this into a report section", "composite.context_to_section"),
        ("Run DCMA on the latest update programme", "composite.dcma_latest"),
        ("Explain why the delay occurred using evidence, and show the supporting documents",
         "composite.evidence_explain"),
    ])
    def test_positive(self, q, expected):
        m = match_composite(q.lower())
        assert m and m["id"] == expected

    @pytest.mark.parametrize("q", [
        "Show milestone movements",            # no chart wording → PROGRAMME
        "Run DCMA check",                      # plain → PROGRAMME fast path
        "total workers in June 2024",          # no chart wording → DATA
        "Who caused the delay?",               # causation → guarded RAG
        "is the contractor entitled to an EOT?",
        "draft a reply letter about the delay",
        "summarise this document",
        "what does this clause mean?",
        "run arbitrary delay analysis",
    ])
    def test_negative(self, q):
        assert match_composite(q.lower()) is None


class TestBlocksContract:
    def test_valid_blocks_pass(self):
        blocks = [
            {"type": "markdown_text", "text": "hello"},
            {"type": "data_table", "title": "t", "columns": ["a"], "rows": [["1"]]},
            {"type": "caveats", "caveats": ["c"], "warnings": []},
        ]
        valid, dropped = validate_blocks(blocks)
        assert len(valid) == 3 and not dropped
        assert valid[0]["block_id"]  # auto-assigned

    def test_unknown_and_invalid_dropped(self):
        blocks = [
            {"type": "markdown_text", "text": "ok"},
            {"type": "run_python", "code": "os.system('rm -rf /')"},
            {"type": "data_table", "title": "t", "columns": ["a", "b"],
             "rows": [["only-one-cell"]]},
            {"type": "artifact_link", "url": "https://evil.example/x",
             "filename": "x"},
            "not-a-dict",
        ]
        valid, dropped = validate_blocks(blocks)
        assert len(valid) == 1
        assert len(dropped) == 4
        assert any("unknown type" in d for d in dropped)
        assert any("row width" in d for d in dropped)
        assert any("/api/artifacts/" in d for d in dropped)

    def test_clarification_is_exclusive(self):
        blocks = [
            {"type": "markdown_text", "text": "x"},
            {"type": "clarification", "question": "which one?", "options": []},
        ]
        valid, dropped = validate_blocks(blocks)
        assert len(valid) == 1 and valid[0]["type"] == "clarification"
        assert any("exclusive" in d for d in dropped)

    def test_html_without_fallback_rejected(self):
        valid, dropped = validate_blocks([
            {"type": "html_report_section", "title": "t", "html": "<p>x</p>",
             "fallback_markdown": "", "sanitized": True}])
        assert not valid and dropped

    def test_response_builder_integration(self):
        from backend.services.response_builder import build_chat_response
        raw = {"query_type": "composite", "answer": "lead-in", "sources": [],
               "blocks": [{"type": "markdown_text", "text": "body"},
                          {"type": "bogus"}]}
        resp = build_chat_response(raw)
        assert resp.ui_intent == "blocks"
        types = [b["type"] for b in resp.blocks]
        assert "markdown_text" in types
        assert "caveats" in types  # dropped-block notice appended

    def test_legacy_response_unchanged(self):
        from backend.services.response_builder import build_chat_response
        raw = {"query_type": "document", "answer": "plain", "sources": []}
        resp = build_chat_response(raw)
        assert resp.blocks is None and resp.ui_intent == "answer"


class TestRetry:
    def test_success_first_try(self):
        r = execute_step("run", "s1", "cap", lambda a: {"v": a})
        assert r.status == "ok" and r.output == {"v": 1} and r.attempts == 1

    def test_retry_then_success(self):
        calls = {"n": 0}
        def fn(attempt):
            calls["n"] += 1
            if attempt == 1:
                raise RuntimeError("flaky")
            return "ok"
        r = execute_step("run", "s1", "cap", fn, RetryPolicy(max_retries=1))
        assert r.status == "ok" and r.attempts == 2

    def test_exhaustion_uses_fallback(self):
        r = execute_step("run", "s1", "cap",
                         lambda a: (_ for _ in ()).throw(RuntimeError("x")),
                         RetryPolicy(max_retries=1, fallback="table"),
                         fallback_fn=lambda reason: {"fallback": True})
        assert r.status == "fallback"
        assert r.output == {"fallback": True}
        assert r.fallback_used == "table"

    def test_failure_without_fallback(self):
        r = execute_step("run", "s1", "cap",
                         lambda a: (None, "no data"))
        assert r.status == "failed" and "no data" in r.reason


class TestChartGuard:
    TABLE = {"title": "t", "columns": ["Trade", "Workers"],
             "rows": [["Mason", 40], ["Electrician", 25], ["Plumber", 10]]}

    def _block(self):
        b, _ = bar_chart_from_table(self.TABLE, "Trade", "Workers", "Workers by trade")
        return b

    def test_exact_copy_passes(self):
        assert chart_guard(self._block(), {"table": self.TABLE,
                                           "category_col": "Trade",
                                           "value_col": "Workers"},
                           "Workers by trade") == []

    def test_mutated_value_rejected(self):
        b = self._block(); b["values"][0] = 99
        v = chart_guard(b, {"table": self.TABLE, "category_col": "Trade",
                            "value_col": "Workers"}, "Workers by trade")
        assert any("diverge" in x for x in v)

    def test_renamed_label_rejected(self):
        b = self._block(); b["categories"][1] = "Sparky"
        v = chart_guard(b, {"table": self.TABLE, "category_col": "Trade",
                            "value_col": "Workers"}, "Workers by trade")
        assert any("categories" in x for x in v)

    def test_llm_title_rejected(self):
        b = self._block(); b["title"] = "Proof the contractor understaffed"
        v = chart_guard(b, {"table": self.TABLE, "category_col": "Trade",
                            "value_col": "Workers"}, "Workers by trade")
        assert any("title" in x for x in v)

    def test_invented_series_rejected_line(self):
        src = [{"name": "MS1", "points": [{"x": "2023-01-01", "y": "2023-02-01"}]}]
        blk = line_chart_from_series(
            src + [{"name": "Ghost", "points": [{"x": "2023-01-01", "y": "2023-03-01"}]}],
            "T")
        v = chart_guard(blk, {"series": src}, "T")
        assert any("invented series" in x for x in v)


class TestLineChartFromTable:
    """Table-derived lines are verified like bars: the guard re-derives the
    points from the source data rather than trusting the builder's output."""

    TABLE = {"title": "t", "columns": ["date_key", "Workers"],
             "rows": [["2025-01", 10], ["2025-02", 20], ["2025-03", 5]]}
    SRC = {"table": TABLE, "x_col": "date_key", "y_col": "Workers"}

    def _block(self, cumulative=False):
        b, _ = line_chart_from_table(self.TABLE, "date_key", "Workers",
                                     "Manpower by month", cumulative=cumulative)
        return b

    def test_points_copied_from_table(self):
        pts = self._block()["series"][0]["points"]
        assert [(p["x"], p["y"]) for p in pts] == [
            ("2025-01", 10.0), ("2025-02", 20.0), ("2025-03", 5.0)]
        assert chart_guard(self._block(), self.SRC, "Manpower by month") == []

    def test_cumulative_running_total(self):
        pts = self._block(cumulative=True)["series"][0]["points"]
        assert [p["y"] for p in pts] == [10.0, 30.0, 35.0]
        src = dict(self.SRC, cumulative=True)
        assert chart_guard(self._block(cumulative=True), src,
                           "Manpower by month") == []

    def test_cumulative_block_fails_a_non_cumulative_source(self):
        v = chart_guard(self._block(cumulative=True), self.SRC,
                        "Manpower by month")
        assert any("diverge" in x for x in v)

    def test_mutated_value_rejected(self):
        b = self._block(); b["series"][0]["points"][1]["y"] = 999
        assert any("diverge" in x for x in
                   chart_guard(b, self.SRC, "Manpower by month"))

    def test_mutated_label_rejected(self):
        b = self._block(); b["series"][0]["points"][0]["x"] = "2099-01"
        assert any("labels/order" in x for x in
                   chart_guard(b, self.SRC, "Manpower by month"))

    def test_appended_point_rejected(self):
        b = self._block(); b["series"][0]["points"].append({"x": "2025-04", "y": 1})
        assert any("points do not match" in x for x in
                   chart_guard(b, self.SRC, "Manpower by month"))

    def test_extra_series_rejected(self):
        b = self._block(); b["series"].append({"name": "Ghost", "points": []})
        assert any("exactly one series" in x for x in
                   chart_guard(b, self.SRC, "Manpower by month"))

    def test_missing_columns_reported(self):
        b, reason = line_chart_from_table(self.TABLE, "nope", "Workers", "T")
        assert b is None and "not in table" in reason
