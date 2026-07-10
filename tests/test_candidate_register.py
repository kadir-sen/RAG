"""Candidate delay event register — store lifecycle + workflow + analyst gate."""

from unittest.mock import patch

from src.delay_reports import candidate_store as cs
from src.delay_reports.schemas import RegisterEntry, RegisterResult, ScopeResult
from src.router import QueryRouter
from src.workflows import plan, run_workflow
from src.workflows.types import WorkflowId


def _entry(date, actor, quote, doc="doc1", fn="notice.pdf", pg=2):
    return RegisterEntry(
        evidence_id="E1", event_date=date, document_date=None, actor=actor,
        recipient=None, action_verb="stated", issue="Access delayed",
        impact=None, requested_action=None, reservation_of_rights=False,
        quote=quote, support_level="verified", file_name=fn, doc_id=doc,
        page_number=pg)


# ── store lifecycle ──────────────────────────────────────────

def test_store_add_confirm_reject_merge():
    corpus = "cs_lifecycle"
    e = [_entry("2024-03-01", "Contractor", "access was delayed on site"),
         _entry("2024-03-05", "Engineer", "instruction issued late")]
    r = cs.add_candidates(e, corpus=corpus, topic="blockwork")
    assert r["ok"] and len(r["ids"]) == 2       # add is idempotent across runs
    c1, c2 = r["ids"][0], r["ids"][1]
    # both candidates are present (freshly inserted or from a prior run)
    assert len(cs.list_candidates(corpus=corpus)) >= 2
    assert cs.set_status(c1, "confirmed", "qa")["ok"]
    assert len(cs.confirmed_events(corpus=corpus)) >= 1
    assert cs.set_status(c2, "rejected", "qa", "not relevant")["ok"]
    assert cs.set_status("nonexistent", "confirmed")["ok"] is False


def test_store_merge_and_guards():
    corpus = "cs_merge"
    e = [_entry("2024-04-01", "Contractor", "delay one", doc="dA"),
         _entry("2024-04-01", "Contractor", "delay two", doc="dB")]
    ids = cs.add_candidates(e, corpus=corpus)["ids"]
    assert cs.merge(ids[0], [ids[1]], "qa")["ok"]
    by_id = {c["candidate_id"]: c for c in cs.list_candidates(corpus=corpus)}
    assert by_id[ids[1]]["status"] == "merged"
    assert by_id[ids[1]]["merged_into"] == ids[0]
    assert cs.merge("", [])["ok"] is False
    assert cs.merge("unknown", ["x"])["ok"] is False


def test_add_is_idempotent():
    corpus = "cs_idem"
    e = [_entry("2024-05-01", "Contractor", "same event text")]
    cs.add_candidates(e, corpus=corpus)
    r2 = cs.add_candidates(e, corpus=corpus)
    assert r2["added"] == 0                     # stable id dedupes


# ── planner routing ──────────────────────────────────────────

def test_register_routes_distinctly_from_chronology():
    assert plan("build a candidate delay event register").workflow_id == \
        WorkflowId.DELAY_EVENT_CANDIDATE_REGISTER
    # a plain 6.1 chronology must NOT be captured by the register
    assert plan("delayed blockwork's chronology in 6.1 format").workflow_id == \
        WorkflowId.DELAY_CHRONOLOGY_SECTION


# ── workflow (LLM/retrieval mocked → deterministic) ──────────

def _stub_router():
    r = QueryRouter.__new__(QueryRouter)
    r._programme_records = lambda doc_ids=None: []
    return r


def test_workflow_persists_candidates_and_flags_analyst():
    scope = ScopeResult(event_title="Delayed Blockwork",
                        topic_terms=["blockwork"])
    ev = [object()]  # retrieval result is opaque to the adapter
    reg = RegisterResult(entries=[
        _entry("2024-06-01", "Contractor", "blockwork access delayed")])
    with patch("src.delay_reports.scope.resolve_event_scope", return_value=scope), \
         patch("src.delay_reports.retrieval.retrieve_evidence", return_value=ev), \
         patch("src.delay_reports.register.build_event_register", return_value=reg), \
         patch("src.document_rag._current_user_corpus", return_value="wf_reg"):
        wr = run_workflow(plan("build a candidate delay event register"),
                          "build a candidate delay event register", _stub_router())
    assert wr.status in ("success", "partial")
    types = [b["type"] for b in wr.blocks]
    assert "data_table" in types and "validation_status" in types
    assert wr.analyst_review_required is True
    # candidate actually persisted for the analyst gate
    assert len(cs.list_candidates(corpus="wf_reg")) >= 1


def test_workflow_no_evidence_returns_clarification():
    scope = ScopeResult(event_title="X", topic_terms=["x"])
    with patch("src.delay_reports.scope.resolve_event_scope", return_value=scope), \
         patch("src.delay_reports.retrieval.retrieve_evidence", return_value=[]), \
         patch("src.document_rag._current_user_corpus", return_value="wf_empty"):
        wr = run_workflow(plan("build a candidate delay event register"),
                          "build a candidate delay event register", _stub_router())
    assert wr.status == "clarification"
    assert [b["type"] for b in wr.blocks] == ["clarification"]


def test_admin_delay_event_endpoints_callable():
    from backend.api.admin import (delay_event_candidates, delay_event_decide,
                                   delay_event_merge, EventDecisionRequest,
                                   EventMergeRequest)
    out = delay_event_candidates(corpus="cs_lifecycle")
    assert out["ok"] and "candidates" in out
    bad = delay_event_decide(EventDecisionRequest(candidate_id="x", action="nope"))
    assert bad["ok"] is False


def test_admin_reject_requires_reason_and_no_hard_delete():
    from backend.api.admin import delay_event_decide, EventDecisionRequest
    e = [_entry("2024-08-01", "Contractor", "reason gate snippet")]
    cid = cs.add_candidates(e, corpus="cs_admin")["ids"][0]
    # reject WITHOUT a reason is refused
    r1 = delay_event_decide(EventDecisionRequest(
        candidate_id=cid, action="reject"))
    assert r1["ok"] is False
    # reject WITH a reason succeeds; the row survives (status change, no delete)
    r2 = delay_event_decide(EventDecisionRequest(
        candidate_id=cid, action="reject", reason="duplicate", decided_by="qa"))
    assert r2["ok"] is True
    got = cs.get_candidate(cid)
    assert got is not None and got["status"] == "rejected"
    assert got["reason"] == "duplicate"


def test_admin_confirmed_and_evidence_endpoints():
    from backend.api.admin import delay_event_confirmed, delay_event_evidence
    e = [_entry("2024-09-01", "Engineer", "evidence endpoint snippet",
                doc="dev", fn="ev.pdf", pg=7)]
    cid = cs.add_candidates(e, corpus="cs_ev")["ids"][0]
    cs.set_status(cid, "confirmed", "qa")
    conf = delay_event_confirmed(corpus="cs_ev")
    assert conf["ok"] and conf["count"] >= 1
    ev = delay_event_evidence(cid)
    assert ev["ok"] and ev["evidence"]["page"] == 7
    assert ev["evidence"]["citation"] == "ev.pdf, p.7"
    assert delay_event_evidence("nonexistent")["ok"] is False
