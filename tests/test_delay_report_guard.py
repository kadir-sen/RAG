"""Chronology narrative guard + deterministic fallback. LLM layer mocked."""

from unittest.mock import patch

import pytest

from src.delay_reports.chronology import build_chronology_table
from src.delay_reports.guard import chronology_guard, chronology_rules
from src.delay_reports.narrative import deterministic_fallback
from src.delay_reports.schemas import (
    RegisterEntry, RegisterResult, ScopeResult, ToolResult,
)


def _entry(date, actor="JAMED", file="L1.pdf", issue="delayed access to buildings"):
    return RegisterEntry(
        evidence_id="E1", event_date=date, document_date=None, actor=actor,
        recipient="BBI-AGC JV", action_verb="raised", issue=issue,
        impact="progress was stated to be affected", requested_action=None,
        reservation_of_rights=True, quote="q", support_level="verified",
        file_name=file, doc_id=file, page_number=3,
    )


@pytest.fixture
def table():
    reg = RegisterResult(entries=[_entry("2023-07-19"),
                                  _entry("2023-07-20", file="L2.pdf")])
    return build_chronology_table(reg, start_index=13)


@pytest.fixture
def scope():
    return ScopeResult(event_title="Delayed Access", topic_terms=["delayed", "access"])


GOOD = (
    "6.1.13 On 19 July 2023, JAMED raised concerns regarding delayed access "
    "to buildings. It reserved its rights. (L1.pdf, p.3)\n\n"
    "6.1.14 On 20 July 2023, JAMED raised concerns regarding delayed access "
    "again. (L2.pdf, p.3)"
)


class TestChronologyRules:
    def test_clean_narrative_passes(self, table, scope):
        assert chronology_rules(GOOD, table, scope) == []

    def test_invented_date_flagged(self, table, scope):
        bad = GOOD.replace("20 July 2023", "25 December 2023")
        assert any("does not appear in the validated register" in v
                   for v in chronology_rules(bad, table, scope))

    def test_out_of_order_paragraphs_flagged(self, table, scope):
        p1, p2 = GOOD.split("\n\n")
        bad = p2 + "\n\n" + p1
        violations = chronology_rules(bad, table, scope)
        assert any("out of order" in v or "missing" in v or "unexpected" in v
                   for v in violations)

    def test_unsourced_paragraph_flagged(self, table, scope):
        bad = GOOD.replace(" (L2.pdf, p.3)", "")
        assert any("no source reference" in v for v in chronology_rules(bad, table, scope))

    def test_wrong_source_file_flagged(self, table, scope):
        bad = GOOD.replace("(L2.pdf, p.3)", "(Ghost.pdf, p.9)")
        assert any("does not match any evidence file" in v
                   for v in chronology_rules(bad, table, scope))

    def test_unknown_party_flagged(self, table, scope):
        bad = GOOD.replace("JAMED raised concerns regarding delayed access again",
                           "Morrison MacDonald raised concerns")
        assert any("unknown party" in v for v in chronology_rules(bad, table, scope))

    def test_missing_paragraph_flagged(self, table, scope):
        bad = GOOD.split("\n\n")[0]
        assert any("missing paragraph" in v for v in chronology_rules(bad, table, scope))

    def test_scope_drift_flagged(self, table):
        drifted_scope = ScopeResult(event_title="Concrete Cracking",
                                    topic_terms=["concrete", "cracking"])
        assert any("does not mention the requested event" in v
                   for v in chronology_rules(GOOD, table, drifted_scope))

    def test_legal_conclusion_flagged(self, table, scope):
        bad = GOOD + "\n\nThis proves JAMED is entitled to an EOT."
        violations = chronology_rules(bad, table, scope)
        assert any("entitlement" in v or "proof" in v for v in violations)


class TestParenthesizedFilenames:
    def test_source_ref_with_parens_in_filename(self):
        reg = RegisterResult(entries=[
            _entry("2023-07-19", file="RE_ Additional items (55).msg")])
        table = build_chronology_table(reg, start_index=1)
        scope = ScopeResult(event_title="Delayed Access",
                            topic_terms=["delayed", "access"])
        narrative = ("6.1.1 On 19 July 2023, JAMED raised concerns regarding "
                     "delayed access. (RE_ Additional items (55).msg, p.3)")
        assert chronology_rules(narrative, table, scope) == []

    def test_fallback_with_paren_filenames_passes_guard(self):
        reg = RegisterResult(entries=[
            _entry("2023-07-19", file="RE_ Additional items (55).msg")])
        table = build_chronology_table(reg, start_index=1)
        scope = ScopeResult(event_title="Delayed Access",
                            topic_terms=["delayed", "access"])
        fb = deterministic_fallback(table, scope.event_title)
        assert chronology_rules(fb, table, scope) == []


class TestFallbackAndGuard:
    def test_fallback_passes_its_own_guard(self, table, scope):
        fb = deterministic_fallback(table, scope.event_title)
        assert chronology_rules(fb, table, scope) == []

    def test_guard_consults_llm_only_when_rules_pass(self, table, scope):
        result = ToolResult(tool_id="delay_reports.event_chronology",
                            summary="s", raw={})
        with patch("src.delay_reports.guard.check_grounding_llm",
                   return_value=[]) as g:
            v = chronology_guard(GOOD, table, scope, result)
        assert g.called and v.approved is True

        bad = GOOD.replace("20 July 2023", "25 December 2023")
        with patch("src.delay_reports.guard.check_grounding_llm") as g2:
            v2 = chronology_guard(bad, table, scope, result)
        assert not g2.called and v2.approved is False
