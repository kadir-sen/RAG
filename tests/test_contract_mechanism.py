"""Contract mechanism extraction MVP — engine + workflow + matrix integration."""

from unittest.mock import patch

from src.delay_reports import candidate_store as cs, contract_mechanism as cm
from src.delay_reports.schemas import RegisterEntry
from src.router import QueryRouter
from src.workflows import plan, run_workflow, is_available
from src.workflows.types import WorkflowId

_CONTRACT = ("The Contractor shall give notice to the Engineer under "
             "Sub-Clause 20.1 within 28 days after becoming aware of the "
             "event. Any claim for an extension of time under Clause 8.4 "
             "shall be submitted within 42 days of the delay.")


def _stub_router():
    r = QueryRouter.__new__(QueryRouter)
    r._programme_records = lambda doc_ids=None: []
    return r


# ── engine ───────────────────────────────────────────────────

def test_extracts_periods_clauses_and_types():
    ms = cm.extract_from_text({1: _CONTRACT}, "contract.pdf", "c1")
    by = {(m.mechanism_type, m.period_days): m for m in ms}
    assert ("notice", 28) in by and by[("notice", 28)].clause_ref == "20.1"
    assert ("eot", 42) in by and by[("eot", 42)].clause_ref == "8.4"


def test_containment_guard_rejects_absent_periods():
    # a period not present in the text can never be produced
    ms = cm.extract_from_text({1: "no periods stated here at all"}, "c.pdf", "c")
    assert ms == []


def test_rules_from_mechanisms():
    ms = cm.extract_from_text({1: _CONTRACT}, "c.pdf", "c1")
    rules = cm.notice_rules_from_mechanisms(ms)
    assert rules["notice"] == 28 and rules["eot"] == 42
    assert rules["default"] in (28, 42)


def test_extraction_never_raises_on_junk():
    assert cm.extract_from_text({}, "", "") == []
    assert cm.extract_from_text(None, "", "") == []


# ── workflow ─────────────────────────────────────────────────

def test_workflow_available_and_routes():
    assert is_available(WorkflowId.CONTRACT_MECHANISM_SUMMARY)
    for p in ("summarise the contract mechanism",
              "what are the notice periods in the contract",
              "contract mechanism extraction"):
        assert plan(p).workflow_id == WorkflowId.CONTRACT_MECHANISM_SUMMARY


def test_workflow_extracts_table_from_contract():
    fake = cm.MechanismResult(
        mechanisms=cm.extract_from_text({1: _CONTRACT}, "contract.pdf", "c1"),
        contract_docs=1, caveats=["verify"])
    with patch("src.document_rag._current_user_corpus", return_value="cmw"), \
         patch("src.delay_reports.contract_mechanism.get_contract_mechanisms",
               return_value=fake):
        wr = run_workflow(plan("contract mechanism extraction"),
                          "contract mechanism extraction", _stub_router())
    assert wr.status == "partial"
    assert wr.analyst_review_required is True
    assert any(b["type"] == "data_table" for b in wr.blocks)


def test_workflow_no_contract_points_elsewhere():
    empty = cm.MechanismResult(mechanisms=[], contract_docs=0, caveats=["none"])
    with patch("src.document_rag._current_user_corpus", return_value="cmnone"), \
         patch("src.delay_reports.contract_mechanism.get_contract_mechanisms",
               return_value=empty):
        wr = run_workflow(plan("contract mechanism extraction"),
                          "contract mechanism extraction", _stub_router())
    assert wr.status == "unavailable"


# ── matrix integration: clause-derived periods override assumed ──

def test_notice_matrix_uses_clause_derived_periods():
    _seed = [RegisterEntry(
        evidence_id="E1", event_date="2024-06-01", document_date=None,
        actor="Contractor", recipient=None, action_verb="stated",
        issue="extension of time", impact=None, requested_action=None,
        reservation_of_rights=False, quote="verbatim snippet here",
        support_level="verified", file_name="n.pdf", doc_id="d1",
        page_number=1)]
    cid = cs.add_candidates(_seed, corpus="cmm", topic="extension of time")["ids"][0]
    cs.set_status(cid, "confirmed", "qa")
    mechs = cm.extract_from_text({1: _CONTRACT}, "contract.pdf", "c1")
    fake = cm.MechanismResult(mechanisms=mechs, contract_docs=1)
    with patch("src.document_rag._current_user_corpus", return_value="cmm"), \
         patch("src.delay_reports.contract_mechanism.get_contract_mechanisms",
               return_value=fake), \
         patch("src.delay_reports.notice_matrix.enumerate_served_notices",
               return_value=[]):
        wr = run_workflow(plan("create notice compliance matrix"),
                          "create notice compliance matrix", _stub_router())
    # caveat now says clause-derived (not assumed); table marks (clause)
    assert any("clause-derived" in c.lower() for c in wr.caveats)
    tbl = next(b for b in wr.blocks if b["type"] == "data_table")
    assert any("(clause)" in str(cell) for row in tbl["rows"] for cell in row)
