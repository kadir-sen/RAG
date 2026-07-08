"""Routing matrix: delay_report vs programme vs RAG/timeline. No LLM."""

import pytest

from src.delay_reports import match_query as dr_match
from src.programme_tools import match_query as prog_match
from src.router import QueryRouter
from src.types import QueryType


def _stub():
    return QueryRouter.__new__(QueryRouter)


class TestRegistryMatrix:
    @pytest.mark.parametrize("q", [
        "Prepare detailed chronology for delayed blockwork",
        "Create 6.1 style chronology for delayed access",
        "prepare delay event narrative section",
        "write chronology of the pending specialist drawings",
        "Find main delay events and prepare chronology",  # routes in → clarification
    ])
    def test_routes_to_delay_report(self, q):
        assert dr_match(q) is not None

    @pytest.mark.parametrize("q", [
        "Run DCMA check",
        "Show milestone movements",
        "Who is responsible for the blockwork delay?",
        "who caused the delay?",
        "is the contractor entitled to an EOT for the delay?",
        "Draft a reply about the delay",
        "summarise the project generally",
        "show manpower histogram for January",
    ])
    def test_does_not_route_to_delay_report(self, q):
        assert dr_match(q) is None

    def test_milestone_chronology_declined_by_both(self):
        q = "prepare chronology of milestone movements"
        # delay_report's negative trigger (milestone) blocks it, and
        # programme's own negative trigger (chronolog) blocks it too — the
        # query falls through to the normal LLM classifier (TIMELINE-ish),
        # which is the documented behavior for this ambiguous phrasing.
        assert dr_match(q) is None
        assert prog_match(q) is None
        # Unambiguous milestone wording still reaches programme.
        assert prog_match("show milestone movements")["id"] == \
            "programme.milestone_shift"

    def test_plain_timeline_stays_out(self):
        # No report/section/chronology-for wording → normal TIMELINE route.
        assert dr_match("show timeline of delays") is None


class TestRouterShortcut:
    def test_classify_delay_report(self):
        d = _stub()._classify_delay_report(
            "prepare detailed chronology for delayed blockwork")
        assert d is not None
        assert d.query_type == QueryType.DELAY_REPORT
        assert d.confidence >= 0.9

    def test_programme_shortcut_takes_precedence_in_classify(self):
        r = _stub()
        # Both could plausibly fire on this; programme is checked first in
        # classify_query, and delay_report's negative trigger also blocks it.
        assert r._classify_programme("run dcma check") is not None
        assert r._classify_delay_report("run dcma check") is None

    def test_agent_gate_excluded(self):
        r = _stub()
        d = r._classify_delay_report("prepare chronology for delayed blockwork")
        assert r._should_use_agent(d, "prepare chronology for delayed blockwork") is False
