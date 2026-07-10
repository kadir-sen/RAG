"""Notice compliance matrix MVP — engine + workflow (prerequisite-gated)."""

from unittest.mock import patch

from backend.models.blocks import validate_blocks
from src.delay_reports import candidate_store as cs, notice_matrix as nm
from src.delay_reports.schemas import RegisterEntry
from src.router import QueryRouter
from src.workflows import plan, run_workflow, is_available
from src.workflows.types import WorkflowId


def _stub_router():
    r = QueryRouter.__new__(QueryRouter)
    r._programme_records = lambda doc_ids=None: []
    return r


def _seed_confirmed(corpus, topic="Delayed Blockwork", date="2024-06-01"):
    e = [RegisterEntry(
        evidence_id="E1", event_date=date, document_date=None,
        actor="Contractor", recipient=None, action_verb="stated",
        issue=topic, impact=None, requested_action=None,
        reservation_of_rights=False, quote="verbatim snippet here",
        support_level="verified", file_name="n.pdf", doc_id="d1",
        page_number=1)]
    cid = cs.add_candidates(e, corpus=corpus, topic=topic)["ids"][0]
    cs.set_status(cid, "confirmed", "qa")


# ── engine ───────────────────────────────────────────────────

def test_engine_in_time_late_not_served_unknown():
    ev = {"event_date": "2024-06-01", "topic": "delay", "actor": "Contractor"}
    notices = [{"date": "2024-06-10", "subject": "notice of delay",
                "sender": "Contractor", "topics": "delay"}]
    m = nm.build_matrix([ev], notices)
    assert m.rows[0].status == "in_time"          # 2024-06-10 <= 2024-06-29
    assert m.rows[0].deadline == "2024-06-29"

    late = nm.build_matrix([ev], [{"date": "2024-08-01",
                                   "subject": "notice of delay",
                                   "sender": "Contractor", "topics": "delay"}])
    assert late.rows[0].status == "late"

    none = nm.build_matrix([ev], [])
    assert none.rows[0].status == "not_served"

    unk = nm.build_matrix([{"event_date": "", "topic": "delay",
                            "actor": "X"}], notices)
    assert unk.rows[0].status == "unknown_date"


def test_engine_always_carries_assumed_and_screening_caveats():
    m = nm.build_matrix([{"event_date": "2024-06-01", "topic": "delay",
                          "actor": "X"}], [])
    joined = " ".join(m.caveats).lower()
    assert "assumed" in joined
    assert "not a determination" in joined or "screening" in joined


def test_required_days_by_topic():
    assert nm._required_days("extension of time claim", nm.DEFAULT_NOTICE_RULES) == 28
    assert nm._required_days("variation instruction", nm.DEFAULT_NOTICE_RULES) == 14
    assert nm._required_days("something else", nm.DEFAULT_NOTICE_RULES) == 28


# ── workflow ─────────────────────────────────────────────────

def test_notice_matrix_is_available_now():
    assert is_available(WorkflowId.NOTICE_COMPLIANCE_MATRIX)
    assert plan("create notice compliance matrix").workflow_id == \
        WorkflowId.NOTICE_COMPLIANCE_MATRIX


def test_no_confirmed_events_states_prerequisite():
    with patch("src.document_rag._current_user_corpus", return_value="nm_none"):
        wr = run_workflow(plan("create notice compliance matrix"),
                          "create notice compliance matrix", _stub_router())
    assert wr.status == "unavailable"
    assert wr.substitute == WorkflowId.DELAY_EVENT_CANDIDATE_REGISTER.value
    assert [b["type"] for b in wr.blocks] == ["markdown_text"]


def test_with_confirmed_builds_matrix_with_analyst_flag():
    _seed_confirmed("nm_have")
    with patch("src.document_rag._current_user_corpus", return_value="nm_have"), \
         patch("src.delay_reports.notice_matrix.enumerate_served_notices",
               return_value=[]):
        wr = run_workflow(plan("create notice compliance matrix"),
                          "create notice compliance matrix", _stub_router())
    assert wr.status == "partial"
    assert wr.analyst_review_required is True
    types = [b["type"] for b in wr.blocks]
    assert "data_table" in types and "validation_status" in types
    assert any("assumed" in c.lower() for c in wr.caveats)
    kept, dropped = validate_blocks(wr.blocks)
    assert dropped == []
