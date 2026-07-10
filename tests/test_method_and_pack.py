"""Method viability + preliminary delay claim pack MVPs."""

from unittest.mock import patch

from src.delay_reports import candidate_store as cs, method_viability as mv
from src.delay_reports.schemas import RegisterEntry
from src.router import QueryRouter
from src.workflows import plan, run_workflow, is_available
from src.workflows.types import WorkflowId


def _router(n_recs=0):
    r = QueryRouter.__new__(QueryRouter)
    recs = [{"doc_id": f"d{i}", "file_name": f"p{i}.xer",
             "file_path": f"/x/p{i}.xer", "status": "completed"}
            for i in range(n_recs)]
    r._programme_records = lambda doc_ids=None: recs
    return r


def _seed_confirmed(corpus):
    e = [RegisterEntry(
        evidence_id="E1", event_date="2024-06-01", document_date=None,
        actor="Contractor", recipient=None, action_verb="stated",
        issue="delay", impact=None, requested_action=None,
        reservation_of_rights=False, quote="snippet here", support_level="verified",
        file_name="n.pdf", doc_id="d1", page_number=1)]
    cid = cs.add_candidates(e, corpus=corpus, topic="Delay")["ids"][0]
    cs.set_status(cid, "confirmed", "qa")


# ── method viability engine ──────────────────────────────────

def test_method_viability_rules():
    full = mv.assess(mv.Availability(baseline=True, programme_updates=True,
                                     confirmed_events=2))
    assert all(r["viable"] for r in full)
    none = mv.assess(mv.Availability())
    assert not any(r["viable"] for r in none)
    # TIA needs baseline + updates + events
    partial = mv.assess(mv.Availability(baseline=True, programme_updates=True,
                                        confirmed_events=0))
    tia = next(r for r in partial if r["key"] == "time_impact_analysis")
    assert tia["viable"] is False


def test_method_viability_workflow():
    assert is_available(WorkflowId.METHOD_VIABILITY)
    with patch("src.document_rag._current_user_corpus", return_value="mvw"), \
         patch("src.delay_reports.notice_matrix.enumerate_served_notices",
               return_value=[]), \
         patch("src.delay_reports.contract_mechanism.get_contract_mechanisms") as g:
        g.return_value.mechanisms = []
        wr = run_workflow(plan("assess delay-analysis method viability"),
                          "assess delay-analysis method viability", _router(2))
    assert wr.status == "partial"
    assert wr.analyst_review_required is True
    assert any(b["type"] == "data_table" for b in wr.blocks)
    assert any("availability screen" in c.lower() or "not a recommendation"
               in c.lower() for c in wr.caveats)


# ── claim pack ───────────────────────────────────────────────

def test_pack_no_data_points_to_register():
    with patch("src.document_rag._current_user_corpus", return_value="pk_empty"):
        wr = run_workflow(plan("generate preliminary delay claim report pack"),
                          "generate preliminary delay claim report pack",
                          _router(0))
    assert wr.status == "unavailable"
    assert wr.substitute == WorkflowId.DELAY_EVENT_CANDIDATE_REGISTER.value


def test_pack_assembles_available_sections():
    _seed_confirmed("pk_have")
    with patch("src.document_rag._current_user_corpus", return_value="pk_have"), \
         patch("src.delay_reports.notice_matrix.enumerate_served_notices",
               return_value=[]), \
         patch("src.delay_reports.contract_mechanism.get_contract_mechanisms") as g:
        g.return_value.mechanisms = []
        wr = run_workflow(plan("generate preliminary delay claim report pack"),
                          "generate preliminary delay claim report pack",
                          _router(0))
    assert wr.status == "partial"
    assert wr.analyst_review_required is True
    text = " ".join(b.get("text", "") for b in wr.blocks if b["type"] == "markdown_text")
    assert "Confirmed delay events" in text and "Method viability" in text
    from backend.models.blocks import validate_blocks
    kept, dropped = validate_blocks(wr.blocks)
    assert dropped == []
