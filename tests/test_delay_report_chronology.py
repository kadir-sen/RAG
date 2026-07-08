"""Chronology table ordering/numbering + scope resolution. No LLM."""

import pytest

from src.delay_reports.chronology import build_chronology_table, table_as_tool_rows
from src.delay_reports.schemas import RegisterEntry, RegisterResult
from src.delay_reports.scope import resolve_event_scope


def _entry(date, actor="JAMED", file="L1.pdf", doc_date=None, **kw):
    base = dict(
        evidence_id="E1", event_date=date, document_date=doc_date,
        actor=actor, recipient="BBI-AGC JV", action_verb="stated",
        issue="delayed access to buildings", impact=None,
        requested_action=None, reservation_of_rights=False,
        quote="q", support_level="verified", file_name=file,
        doc_id=file, page_number=1,
    )
    base.update(kw)
    return RegisterEntry(**base)


class TestChronologyTable:
    def test_sorted_by_event_date_and_numbered(self):
        reg = RegisterResult(entries=[
            _entry("2024-06-30"), _entry("2023-07-19"), _entry("2023-07-20"),
        ])
        table = build_chronology_table(reg, section_base="6.1", start_index=12)
        assert [r.date for r in table.rows] == ["2023-07-19", "2023-07-20", "2024-06-30"]
        assert [r.para_no for r in table.rows] == ["6.1.12", "6.1.13", "6.1.14"]

    def test_document_date_fallback_with_caveat(self):
        reg = RegisterResult(entries=[
            _entry("2023-07-19"),
            _entry(None, doc_date="2023-08-01"),
        ])
        table = build_chronology_table(reg)
        assert len(table.rows) == 2
        assert table.rows[1].date_is_document_date is True
        assert any("document date" in c for c in table.caveats)

    def test_register_caveats_carried(self):
        reg = RegisterResult(entries=[_entry("2023-07-19")],
                             caveats=["3 item(s) excluded"])
        table = build_chronology_table(reg)
        assert "3 item(s) excluded" in table.caveats

    def test_tool_rows_shape(self):
        reg = RegisterResult(entries=[_entry("2023-07-19",
                                             reservation_of_rights=True)])
        rows = table_as_tool_rows(build_chronology_table(reg))
        assert rows[0][0] == "6.1.1"
        assert "19 July 2023" in rows[0][1]
        assert rows[0][5] == "reserved rights"
        assert rows[0][6] == "L1.pdf, p.1"


class TestScopeResolution:
    @pytest.mark.parametrize("q,title", [
        ("Prepare detailed chronology for Delayed Blockwork", "Delayed Blockwork"),
        ("prepare chronology of the delayed access event", "delayed access"),
        ("Create 6.1 style chronology for delayed access", "delayed access"),
        ("For the Pending Specialist Drawings event, prepare the report narrative",
         "Pending Specialist Drawings"),
    ])
    def test_title_extracted(self, q, title):
        scope = resolve_event_scope(q)
        assert scope.event_title == title
        assert scope.needs_clarification is False

    def test_generic_request_clarifies(self):
        scope = resolve_event_scope("Find main delay events and prepare chronology")
        assert scope.needs_clarification is True
        assert "name the delay event" in scope.clarification

    def test_router_topic_fallback(self):
        class FakeRouter:
            def compute_query_scope(self, q):
                return {"topic": "delayed blockwork", "actor": "JAMED"}
        scope = resolve_event_scope("chronology please", FakeRouter())
        # regex fails ("chronology please" has no for/of tail) → LLM topic used
        assert scope.event_title == "delayed blockwork"
        assert scope.parties == ["JAMED"]

    def test_topic_terms(self):
        scope = resolve_event_scope("Prepare chronology for Delayed Blockwork")
        assert "delayed" in scope.topic_terms and "blockwork" in scope.topic_terms
