"""Confirmed-event → 6.1 chronology integration (non-breaking wrapper)."""

from unittest.mock import patch

from src.delay_reports import candidate_store as cs
from src.delay_reports.schemas import RegisterEntry
from src.router import QueryRouter
from src.workflows import plan, run_workflow
from src.workflows.adapters import delay_chronology as adp
from src.workflows.types import WorkflowId


def _stub_router():
    r = QueryRouter.__new__(QueryRouter)
    r._programme_records = lambda doc_ids=None: []
    r._current_question = staticmethod(lambda q: q)
    return r


def _seed_confirmed(corpus, topic="Delayed Blockwork"):
    e = [RegisterEntry(
        evidence_id="E1", event_date="2024-06-01", document_date=None,
        actor="Contractor", recipient=None, action_verb="stated",
        issue="blockwork access delayed", impact=None, requested_action=None,
        reservation_of_rights=False, quote="blockwork access was delayed",
        support_level="verified", file_name="notice.pdf", doc_id="dbw",
        page_number=2)]
    cid = cs.add_candidates(e, corpus=corpus, topic=topic)["ids"][0]
    cs.set_status(cid, "confirmed", "qa")


def test_confirmed_scope_derives_query_and_docids():
    _seed_confirmed("cc_scope", "Delayed Blockwork")
    with patch("src.document_rag._current_user_corpus", return_value="cc_scope"):
        scope = adp._confirmed_scope("prepare 6.1 chronology for confirmed event 01")
    assert scope and "query" in scope
    assert scope["doc_ids"] == ["dbw"]           # prioritises confirmed evidence
    assert "Delayed Blockwork" in scope["query"]


def test_confirmed_without_any_confirmed_events_clarifies():
    with patch("src.document_rag._current_user_corpus", return_value="cc_none"):
        wr = run_workflow(
            plan("prepare 6.1 chronology for confirmed event 01"),
            "prepare 6.1 chronology for confirmed event 01", _stub_router())
    assert wr.status == "clarification"
    assert "confirm" in wr.answer.lower()


def test_plain_chronology_is_not_treated_as_confirmed():
    # No "confirmed" keyword → the wrapper stays out of the way (regression).
    assert adp._confirmed_scope("delayed blockwork's chronology in 6.1 format") \
        is None


def test_confirmed_chronology_runs_through_existing_handler():
    _seed_confirmed("cc_run", "Delayed Blockwork")
    fake = {"answer": "6.1.1 On 2024-06-01 …", "query_type": "delay_report",
            "programme_artifact": {"tables": [{"title": "Chronology",
                "columns": ["Ref", "Event"], "rows": [["6.1.1", "x"]]}],
                "caveats": [], "requires_analyst_review": True, "validation": {}},
            "sources": []}
    with patch("src.document_rag._current_user_corpus", return_value="cc_run"), \
         patch("src.delay_reports.run_event_chronology", return_value=fake) as h:
        wr = run_workflow(
            plan("prepare 6.1 chronology for confirmed event 01"),
            "prepare 6.1 chronology for confirmed event 01", _stub_router())
    assert wr.status in ("success", "partial")
    assert wr.analyst_review_required is True
    # the derived query (not the raw "confirmed event 01") reached the handler
    called_query = h.call_args[0][0]
    assert "Delayed Blockwork" in called_query
