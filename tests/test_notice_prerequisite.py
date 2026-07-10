"""Notice compliance matrix — prerequisite-aware planned response."""

from unittest.mock import patch

from backend.models.blocks import validate_blocks
from src.delay_reports import candidate_store as cs
from src.delay_reports.schemas import RegisterEntry
from src.router import QueryRouter
from src.workflows import plan, run_workflow
from src.workflows.types import WorkflowId


def _stub_router():
    r = QueryRouter.__new__(QueryRouter)
    r._programme_records = lambda doc_ids=None: []
    return r


def _seed_confirmed(corpus):
    e = [RegisterEntry(
        evidence_id="E1", event_date="2024-06-01", document_date=None,
        actor="Contractor", recipient=None, action_verb="stated",
        issue="late notice", impact=None, requested_action=None,
        reservation_of_rights=False, quote="notice served late here",
        support_level="verified", file_name="n.pdf", doc_id="dn",
        page_number=1)]
    cid = cs.add_candidates(e, corpus=corpus, topic="Late Notice")["ids"][0]
    cs.set_status(cid, "confirmed", "qa")


def test_no_confirmed_states_prerequisite_and_substitute():
    with patch("src.document_rag._current_user_corpus", return_value="nm_none"):
        wr = run_workflow(plan("create notice compliance matrix"),
                          "create notice compliance matrix", _stub_router())
    assert wr.status == "unavailable"
    assert "requires" in wr.answer.lower() and "confirmed delay events" in \
        wr.answer.lower()
    assert wr.substitute == WorkflowId.DELAY_EVENT_CANDIDATE_REGISTER.value
    # not a generic error, not a clarification block
    assert [b["type"] for b in wr.blocks] == ["markdown_text"]


def test_with_confirmed_lists_events_and_points_forward():
    _seed_confirmed("nm_have")
    with patch("src.document_rag._current_user_corpus", return_value="nm_have"):
        wr = run_workflow(plan("create notice compliance matrix"),
                          "create notice compliance matrix", _stub_router())
    assert wr.status == "unavailable"
    types = [b["type"] for b in wr.blocks]
    assert "markdown_text" in types and "data_table" in types
    assert wr.substitute == WorkflowId.EVENT_EVIDENCE_TABLE.value


def test_response_passes_block_contract():
    with patch("src.document_rag._current_user_corpus", return_value="nm_ct"):
        wr = run_workflow(plan("create notice compliance matrix"),
                          "create notice compliance matrix", _stub_router())
    kept, dropped = validate_blocks(wr.blocks)
    assert dropped == []
    assert "clarification" not in [b["type"] for b in kept]
