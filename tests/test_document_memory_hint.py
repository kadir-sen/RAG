"""document_memory surfaced as a VISIBLE, confirmation-gated hint in the
executor's input-resolution summary — never a silent reuse."""

from unittest.mock import patch

import pytest

import src.learning.document_memory as dm
from src.delay_reports import candidate_store as cs
from src.delay_reports.schemas import RegisterEntry
from src.router import QueryRouter
from src.workflows import plan, run_workflow
from src.workflows.types import WorkflowId


@pytest.fixture(autouse=True)
def isolated_doc_mem(tmp_path, monkeypatch):
    monkeypatch.setattr(dm, "_STORE", tmp_path / "document_memory.json")
    yield


def _stub_router():
    r = QueryRouter.__new__(QueryRouter)
    r._programme_records = lambda doc_ids=None: []
    r._current_question = staticmethod(lambda q: q)
    return r


def _seed_confirmed(corpus):
    e = [RegisterEntry(
        evidence_id="E1", event_date="2024-06-01", document_date=None,
        actor="Contractor", recipient=None, action_verb="stated",
        issue="x", impact=None, requested_action=None,
        reservation_of_rights=False, quote="snippet text here",
        support_level="verified", file_name="n.pdf", doc_id="d1",
        page_number=1)]
    cid = cs.add_candidates(e, corpus=corpus, topic="Blockwork")["ids"][0]
    cs.set_status(cid, "confirmed", "qa")


def _summary_text(wr):
    b = wr.blocks[0]
    return b["text"] if b.get("block_id") == "input_resolution" else ""


def test_approved_selection_shown_as_visible_hint():
    akey = dm.analysis_key(WorkflowId.EVENT_EVIDENCE_TABLE.value, "Blockwork")
    dm.confirm_selection(akey, ["d1", "d2"], corpus="dmh")
    _seed_confirmed("dmh")
    with patch("src.document_rag._current_user_corpus", return_value="dmh"), \
         patch("src.delay_reports.scope.resolve_event_scope") as rs:
        rs.return_value.event_title = "Blockwork"
        wr = run_workflow(plan("show evidence for event 01"),
                          "show evidence for event 01", _stub_router())
    # visible in the input-resolution summary; NOT silently applied
    assert "previously approved documents" in _summary_text(wr).lower()
    assert wr.debug_trace.get("memory_hint_used") is True


def test_unapproved_selection_is_not_suggested():
    akey = dm.analysis_key(WorkflowId.EVENT_EVIDENCE_TABLE.value, "Blockwork")
    dm.record_selection(akey, ["d1"], corpus="dmh2", approved=False)
    _seed_confirmed("dmh2")
    with patch("src.document_rag._current_user_corpus", return_value="dmh2"), \
         patch("src.delay_reports.scope.resolve_event_scope") as rs:
        rs.return_value.event_title = "Blockwork"
        wr = run_workflow(plan("show evidence for event 01"),
                          "show evidence for event 01", _stub_router())
    assert "previously approved documents" not in _summary_text(wr).lower()
    assert wr.debug_trace.get("memory_hint_used") is False


def test_other_project_selection_never_leaks():
    akey = dm.analysis_key(WorkflowId.EVENT_EVIDENCE_TABLE.value, "Blockwork")
    dm.confirm_selection(akey, ["d1"], corpus="proj_a")
    _seed_confirmed("proj_b")
    with patch("src.document_rag._current_user_corpus", return_value="proj_b"), \
         patch("src.delay_reports.scope.resolve_event_scope") as rs:
        rs.return_value.event_title = "Blockwork"
        wr = run_workflow(plan("show evidence for event 01"),
                          "show evidence for event 01", _stub_router())
    assert wr.debug_trace.get("memory_hint_used") is False
