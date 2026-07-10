"""Event evidence table workflow — from confirmed events only."""

from unittest.mock import patch

from src.delay_reports import candidate_store as cs
from src.delay_reports.schemas import RegisterEntry
from src.router import QueryRouter
from src.workflows import plan, run_workflow
from src.workflows.types import WorkflowId


def _stub_router():
    r = QueryRouter.__new__(QueryRouter)
    r._programme_records = lambda doc_ids=None: []
    return r


def _seed_confirmed(corpus, n=2):
    entries = [RegisterEntry(
        evidence_id=f"E{i}", event_date=f"2024-0{i+1}-01", document_date=None,
        actor="Contractor", recipient=None, action_verb="stated",
        issue=f"issue {i}", impact=None, requested_action=None,
        reservation_of_rights=False, quote=f"verbatim snippet {i} here",
        support_level="verified", file_name=f"n{i}.pdf", doc_id=f"d{i}",
        page_number=i + 1) for i in range(n)]
    ids = cs.add_candidates(entries, corpus=corpus)["ids"]
    for cid in ids:
        cs.set_status(cid, "confirmed", "qa")
    return ids


def _types(wr):
    return [b["type"] for b in wr.blocks]


def test_planner_routes_evidence_table():
    assert plan("show evidence table for confirmed delay events").workflow_id \
        == WorkflowId.EVENT_EVIDENCE_TABLE
    assert plan("which documents support event 01").workflow_id \
        == WorkflowId.EVENT_EVIDENCE_TABLE


def test_no_confirmed_events_points_to_register():
    with patch("src.document_rag._current_user_corpus", return_value="eet_empty"):
        wr = run_workflow(plan("show evidence table for confirmed delay events"),
                          "show evidence table for confirmed delay events",
                          _stub_router())
    assert wr.status == "unavailable"
    assert _types(wr) == ["markdown_text"]
    assert wr.substitute == WorkflowId.DELAY_EVENT_CANDIDATE_REGISTER.value


def test_multiple_confirmed_requires_selection():
    _seed_confirmed("eet_multi", 2)
    with patch("src.document_rag._current_user_corpus", return_value="eet_multi"):
        wr = run_workflow(plan("show evidence table for confirmed delay events"),
                          "show evidence table for confirmed delay events",
                          _stub_router())
    assert wr.status == "clarification"
    assert "data_table" in _types(wr)          # shows the list to pick from


def test_selected_event_yields_evidence_table():
    _seed_confirmed("eet_pick", 2)
    with patch("src.document_rag._current_user_corpus", return_value="eet_pick"):
        wr = run_workflow(plan("show evidence for event 01"),
                          "show evidence for event 01", _stub_router())
    assert wr.status == "success"
    t = _types(wr)
    assert "data_table" in t and "validation_status" in t
    assert wr.analyst_review_required is True
    ev = next(b for b in wr.blocks if b["type"] == "data_table")
    assert "Citation" in ev["columns"] and "Snippet" in ev["columns"]


def test_event_out_of_range_clarifies():
    _seed_confirmed("eet_range", 1)
    with patch("src.document_rag._current_user_corpus", return_value="eet_range"):
        wr = run_workflow(plan("show evidence for event 09"),
                          "show evidence for event 09", _stub_router())
    assert wr.status == "clarification"


def test_cross_project_isolation():
    _seed_confirmed("eet_p1", 1)
    with patch("src.document_rag._current_user_corpus", return_value="eet_p2"):
        wr = run_workflow(plan("show evidence table for confirmed delay events"),
                          "show evidence table for confirmed delay events",
                          _stub_router())
    assert wr.status == "unavailable"          # p1's confirmed events invisible
