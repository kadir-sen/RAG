"""Composite runner tests — LLM/analyzer/retrieval mocked; XER fixtures real."""

from pathlib import Path
from unittest.mock import patch

import pytest

from src.orchestration import run_composite
from src.orchestration.executor import RunContext
from src.orchestration import runners
from src.router import QueryRouter
from src.types import QueryType

FIXTURES = Path(__file__).parent / "fixtures" / "xer"


def _records(n=3):
    paths = sorted(FIXTURES.glob("*.xer"))[:n]
    return [{"doc_id": p.stem, "file_name": p.name, "file_path": str(p),
             "status": "completed"} for p in paths]


def _stub_router(records=None):
    r = QueryRouter.__new__(QueryRouter)
    recs = records if records is not None else _records()
    r._programme_records = lambda doc_ids=None: recs
    return r


@pytest.fixture(autouse=True)
def artifacts_tmp(tmp_path, monkeypatch):
    import src.programme_tools.config_paths as cp
    monkeypatch.setattr(cp, "artifacts_dir", lambda: tmp_path)
    yield


def _block_types(result):
    return [b["type"] for b in result.blocks]


class TestMilestoneShiftVisual:
    def test_end_to_end_blocks(self):
        with patch("src.programme_tools.narrative.compose_narrative",
                   side_effect=lambda res, ctx=None, use_llm=True: res.summary):
            out = run_composite("composite.milestone_shift_visual",
                                "show milestone movements as a chart", {},
                                _stub_router())
        assert out.status in ("success", "partial")
        types = _block_types(out)
        assert "markdown_text" in types
        assert "chart" in types            # chart passed the guard
        assert "data_table" in types
        assert "validation_status" in types
        assert out.primary_artifact["tool_id"] == "programme.milestone_shift"

    def test_too_few_revisions_clarifies(self):
        out = run_composite("composite.milestone_shift_visual",
                            "show milestone movements as a chart", {},
                            _stub_router(_records(1)))
        assert out.status == "needs_clarification"
        assert _block_types(out) == ["clarification"]

    def test_unknown_intent_refused(self):
        out = run_composite("composite.run_python", "x", {}, _stub_router())
        assert out.status == "failed"
        assert "not a registered capability" in out.answer


class TestSqlMetricChart:
    def _fake_analyzer(self, df_map):
        import pandas as pd

        class Fake:
            tables = {"mp1": {"header_metadata": {"target_schema": "manpower_production"},
                              "corpus": "demo"},
                      "mp1_clean": {}}
            def get_tables_for_corpus(self, corpus):
                return None
            def execute_raw_sql(self, sql):
                return df_map.get("df"), df_map.get("err", "")
        return Fake()

    def test_happy_bar_chart(self):
        import pandas as pd
        df = pd.DataFrame({"category": ["Mason", "Electrician"],
                           "value": [40.0, 25.0]})
        fake = self._fake_analyzer({"df": df})
        with patch("src.data_analyzer_sql.get_data_analyzer", return_value=fake):
            out = run_composite("composite.sql_metric_chart",
                                "create a bar chart of manpower by trade for June 2024",
                                {}, _stub_router())
        assert out.status == "success"
        types = _block_types(out)
        assert "chart" in types and "data_table" in types
        chart = next(b for b in out.blocks if b["type"] == "chart")
        assert chart["chart_type"] == "bar"
        assert chart["values"] == [40.0, 25.0]
        assert "2024-06" in chart["title"]

    def test_month_without_year_clarifies(self):
        import pandas as pd
        fake = self._fake_analyzer({"df": pd.DataFrame()})
        with patch("src.data_analyzer_sql.get_data_analyzer", return_value=fake):
            out = run_composite("composite.sql_metric_chart",
                                "bar chart of manpower by trade for June", {},
                                _stub_router())
        assert out.status == "needs_clarification"
        assert "year" in out.blocks[0]["question"].lower()

    def test_no_rows_clarifies(self):
        import pandas as pd
        fake = self._fake_analyzer({"df": pd.DataFrame()})
        with patch("src.data_analyzer_sql.get_data_analyzer", return_value=fake):
            out = run_composite("composite.sql_metric_chart",
                                "bar chart of manpower by trade for June 2024",
                                {}, _stub_router())
        assert out.status == "needs_clarification"


class TestChronologyHtml:
    def test_html_section_from_chronology(self):
        chron_out = {
            "answer": "6.1.1 On 19 July 2023, JAMED raised concerns. (L1.pdf, p.3)",
            "query_type": "delay_report",
            "programme_artifact": {
                "tool_id": "delay_reports.event_chronology",
                "status": "complete",
                "summary": "Chronology for 'Delayed Blockwork': 1 dated paragraph(s)",
                "tables": [{"title": "Chronology", "columns": ["Date"],
                            "rows": [["19 July 2023"]]}],
                "caveats": ["parties' claims"], "warnings": [],
                "requires_analyst_review": False,
                "validation": {"computation_guard": {"pre": "passed",
                                                     "post": "passed"}},
            },
            "sources": [{"file_name": "L1.pdf", "page_number": 3}],
        }
        with patch("src.delay_reports.run_event_chronology",
                   return_value=chron_out):
            out = run_composite("composite.chronology_html",
                                "prepare 6.1 chronology for delayed blockwork "
                                "as an html report section", {}, _stub_router())
        assert out.status in ("success", "partial")
        html_blocks = [b for b in out.blocks if b["type"] == "html_report_section"]
        assert html_blocks and "coair-sources" in html_blocks[0]["html"]
        assert html_blocks[0]["fallback_markdown"]

    def test_chronology_clarification_passthrough(self):
        with patch("src.delay_reports.run_event_chronology",
                   return_value={"clarification": True,
                                 "answer": "Please name the delay event."}):
            out = run_composite("composite.chronology_html",
                                "chronology as html report section", {},
                                _stub_router())
        assert out.status == "needs_clarification"


class TestContextToSection:
    def test_uses_previous_artifact(self):
        art = {"tool_id": "programme.dcma_14_point", "status": "complete",
               "summary": "DCMA 14-point on revA.xer: 9 pass / 4 fail / 1 N/A.",
               "tables": [{"title": "Scorecard", "columns": ["#"], "rows": [["1"]]}],
               "caveats": ["screening guidance"],
               "requires_analyst_review": False,
               "validation": {"computation_guard": {"post": "passed"}}}
        out = run_composite("composite.context_to_section",
                            "make this into a report section", {},
                            _stub_router(), context_artifact=art)
        assert out.status in ("success", "partial")
        assert any(b["type"] == "html_report_section" for b in out.blocks)

    def test_no_context_clarifies(self):
        out = run_composite("composite.context_to_section",
                            "make this into a report section", {},
                            _stub_router(), context_artifact=None)
        assert out.status == "needs_clarification"


class TestDcmaLatest:
    def test_resolver_pick_and_run(self):
        recs = _records(3)
        picked = {"doc_id": recs[-1]["doc_id"], "file_name": recs[-1]["file_name"],
                  "file_path": recs[-1]["file_path"],
                  "meta": {"data_date": "2026-01-01"}}
        from src.orchestration.resolver import ResolveOutcome
        ok = ResolveOutcome(resolved={"current_xer": picked})
        with patch("src.orchestration.resolver.resolve_xer", return_value=ok), \
             patch("src.programme_tools.narrative.compose_narrative",
                   side_effect=lambda res, ctx=None, use_llm=True: res.summary):
            out = run_composite("composite.dcma_latest",
                                "run dcma on the latest update programme", {},
                                _stub_router())
        assert out.status in ("success", "partial")
        assert any(b["type"] == "data_table" and len(b["rows"]) == 14
                   for b in out.blocks)
        assert any("selected automatically" in c
                   for b in out.blocks if b["type"] == "caveats"
                   for c in b["caveats"])

    def test_ambiguous_clarifies_with_options(self):
        from src.orchestration.resolver import ResolveOutcome
        amb = ResolveOutcome(needs_confirmation=True,
                             clarification="Multiple programmes share the latest data date — which one?",
                             options=[{"label": "a.xer", "value": "use a.xer"}])
        with patch("src.orchestration.resolver.resolve_xer", return_value=amb):
            out = run_composite("composite.dcma_latest",
                                "run dcma on the latest programme", {},
                                _stub_router())
        assert out.status == "needs_clarification"
        assert out.blocks[0]["options"]


class TestEvidenceExplain:
    def test_high_risk_flow(self):
        from src.delay_reports.schemas import EvidenceItem, RegisterEntry, RegisterResult
        ev = [EvidenceItem("E1", "L1.pdf", "L1.pdf", 3, "snippet")]
        reg = RegisterResult(entries=[RegisterEntry(
            "E1", "2023-07-19", None, "JAMED", None, "raised",
            "delayed access to buildings", None, None, False,
            "quote text", "verified", "L1.pdf", "L1.pdf", 3)])

        class FakeVerdict:
            skipped = False
            action = "approve"

        with patch.object(runners, "_programme_records", return_value=[]), \
             patch("src.delay_reports.retrieval.retrieve_evidence",
                   return_value=ev), \
             patch("src.delay_reports.register.build_event_register",
                   return_value=reg), \
             patch("src.trust_guard.run_trust_guard_on_result",
                   return_value=FakeVerdict()):
            out = run_composite(
                "composite.evidence_explain",
                "explain why the delay occurred using evidence and show the "
                "supporting documents", {}, _stub_router())
        assert out.status == "partial"  # analyst review always required
        types = _block_types(out)
        assert "markdown_text" in types and "data_table" in types
        narrative = next(b for b in out.blocks if b["type"] == "markdown_text")
        assert "does not establish causation" in narrative["text"]
        caveats = next(b for b in out.blocks if b["type"] == "caveats")
        assert any("not a causation" in c for c in caveats["caveats"])
        validation = next(b for b in out.blocks if b["type"] == "validation_status")
        assert validation["requires_analyst_review"] is True
        assert validation["guards"].get("trust_guard") in ("passed", "fallback",
                                                           "skipped")

    def test_no_evidence_clarifies(self):
        with patch("src.delay_reports.retrieval.retrieve_evidence",
                   return_value=[]):
            out = run_composite(
                "composite.evidence_explain",
                "explain why the delay occurred using evidence", {},
                _stub_router())
        assert out.status == "needs_clarification"


class TestRouterIntegration:
    def _stub(self):
        return QueryRouter.__new__(QueryRouter)

    def test_classify_composite(self):
        d = self._stub()._classify_composite("show milestone movements as a chart")
        assert d is not None and d.query_type == QueryType.COMPOSITE

    def test_composite_beats_programme(self):
        r = self._stub()
        q = "show milestone movements as a chart"
        assert r._classify_composite(q) is not None
        # programme shortcut would also match; composite is checked first in
        # both chains — locked here by asserting composite fires.

    def test_agent_gate_excluded(self):
        r = self._stub()
        d = r._classify_composite("show milestone movements as a chart")
        assert r._should_use_agent(d, "show milestone movements as a chart") is False

    def test_dispatch_routes_composite(self):
        r = self._stub()
        with patch.object(QueryRouter, "_handle_composite_query",
                          return_value={"answer": "ok", "query_type": "composite",
                                        "blocks": []}) as h:
            out = r._dispatch_query(QueryType.COMPOSITE, "q", "q", None)
        assert h.called and out["query_type"] == "composite"

    def test_handler_produces_blocks(self):
        r = self._stub()
        r._programme_records = lambda doc_ids=None: _records()
        with patch("src.programme_tools.narrative.compose_narrative",
                   side_effect=lambda res, ctx=None, use_llm=True: res.summary), \
             patch("src.router.QueryRouter._current_question",
                   side_effect=lambda q: q):
            out = r._handle_composite_query("show milestone movements as a chart")
        assert out["query_type"] == "composite"
        assert out["blocks"]
        assert out.get("programme_artifact")
