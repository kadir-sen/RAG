"""delay_briefing workflow — the single-prompt project briefing.

Composition only: every section comes from a workflow tested elsewhere, so
these tests are about what gets included, what gets left out, and what the
briefing says about the difference.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.models.blocks import validate_blocks
from src.workflows.adapters import delay_briefing as db
from src.workflows.types import (RESULT_PARTIAL, RESULT_SUCCESS,
                                 RESULT_UNAVAILABLE, WorkflowId,
                                 WorkflowResult)

CONFIRMED = [{"event_date": "2023-07-19", "actor": "JAMED",
              "issue": "Access not granted", "file_name": "L1.pdf",
              "page_number": 3}]


def _wr(wid, blocks, caveats=(), status=RESULT_PARTIAL):
    return WorkflowResult(workflow_id=wid, status=status, blocks=list(blocks),
                          caveats=list(caveats))


class FakeRouter:
    def __init__(self, n_records=0):
        self._records = [{"doc_id": f"x{i}"} for i in range(n_records)]

    def _programme_records(self, doc_ids=None):
        return self._records


@pytest.fixture
def stubs(monkeypatch):
    """Every sub-workflow stubbed; each test opts into what data exists."""
    state = {
        "confirmed": [],
        "inventory": _wr(WorkflowId.PROGRAMME_INVENTORY,
                         [{"type": "data_table", "block_id": "t",
                           "title": "Programme inventory",
                           "columns": ["Rev"], "rows": [["R1"]]}]),
        "notice": _wr(WorkflowId.NOTICE_COMPLIANCE_MATRIX,
                      [{"type": "data_table", "block_id": "n",
                        "title": "Notice compliance",
                        "columns": ["Event"], "rows": [["1"]]}],
                      caveats=["Notice periods are assumed."]),
        "monthly": _wr(WorkflowId.MONTHLY_PROGRESS_REPORT,
                       [{"type": "markdown_text", "block_id": "lead",
                         "text": "**Monthly progress report**"},
                        {"type": "chart", "block_id": "c", "chart_type": "bar",
                         "title": "Manpower by trade", "categories": ["Mason"],
                         "values": [10.0]}],
                       caveats=["This is a progress record only."]),
        "milestone_blocks": ([{"type": "chart", "block_id": "ms",
                               "chart_type": "line", "title": "Milestone shift",
                               "series": [{"name": "MS1", "points": []}]}], []),
    }
    monkeypatch.setattr("src.delay_reports.candidate_store.confirmed_events",
                        lambda corpus="", project_id=None: state["confirmed"])
    monkeypatch.setattr(db, "corpus_id", lambda: "demo")
    monkeypatch.setattr("src.workflows.adapters.programme_inventory.run",
                        lambda *a, **k: state["inventory"])
    monkeypatch.setattr("src.workflows.adapters.notice_matrix.run",
                        lambda *a, **k: state["notice"])
    monkeypatch.setattr("src.workflows.adapters.monthly_progress_report.run",
                        lambda *a, **k: state["monthly"])
    monkeypatch.setattr(db, "_composite_blocks",
                        lambda *a, **k: state["milestone_blocks"])
    return state


def _caveats(wr):
    for b in wr.blocks:
        if b["type"] == "caveats":
            return b.get("caveats", [])
    return []


def _text(wr):
    return "\n".join(b.get("text", "") for b in wr.blocks
                     if b["type"] == "markdown_text")


class TestFullBriefing:
    def test_assembles_every_section_from_one_prompt(self, stubs):
        stubs["confirmed"] = CONFIRMED
        wr = db.run("Generate a monthly progress and delay briefing for this "
                    "project.", FakeRouter(2))
        assert wr.status == RESULT_PARTIAL
        text = _text(wr)
        for section in ["Programme summary", "Milestone movement",
                        "Confirmed delay events", "Notice compliance",
                        "Progress record"]:
            assert section in text, f"{section} missing"
        assert wr.analyst_review_required is True

    def test_sections_are_numbered_in_order(self, stubs):
        stubs["confirmed"] = CONFIRMED
        wr = db.run("delay briefing", FakeRouter(2))
        headings = [b["text"] for b in wr.blocks
                    if b["type"] == "markdown_text" and b["text"].startswith("## ")]
        assert [h.split(".")[0] for h in headings] == ["## 1", "## 2", "## 3",
                                                       "## 4", "## 5"]

    def test_carries_the_sub_workflow_caveats_through(self, stubs):
        stubs["confirmed"] = CONFIRMED
        wr = db.run("delay briefing", FakeRouter(2))
        caveats = _caveats(wr)
        assert any("Notice periods are assumed" in c for c in caveats)
        assert any("progress record only" in c for c in caveats)

    def test_never_presents_itself_as_a_finding(self, stubs):
        stubs["confirmed"] = CONFIRMED
        wr = db.run("delay briefing", FakeRouter(2))
        assert "not a submission" in wr.answer
        caveats = _caveats(wr)
        assert any("Analyst review is required" in c for c in caveats)
        assert any("preliminary draft" in c for c in caveats)


class TestPartialData:
    def test_no_confirmed_events_drops_events_and_notice_sections(self, stubs):
        wr = db.run("delay briefing", FakeRouter(2))
        text = _text(wr)
        assert "Confirmed delay events" not in text
        assert "Notice compliance" not in text
        assert any("No analyst-confirmed delay events" in c
                   for c in _caveats(wr))
        # ...the rest of the briefing still renders.
        assert "Programme summary" in text
        assert "Progress record" in text

    def test_single_revision_drops_milestone_movement_with_a_caveat(self, stubs):
        wr = db.run("delay briefing", FakeRouter(1))
        assert "Milestone movement" not in _text(wr)
        assert any("one dated programme revision" in c for c in _caveats(wr))

    def test_no_programme_still_briefs_on_progress(self, stubs):
        wr = db.run("delay briefing", FakeRouter(0))
        text = _text(wr)
        assert "Programme summary" not in text
        assert "Progress record" in text
        assert wr.status == RESULT_PARTIAL

    def test_milestone_movement_is_never_called_causation(self, stubs):
        wr = db.run("delay briefing", FakeRouter(2))
        assert any("not evidence of causation" in c for c in _caveats(wr))

    def test_unavailable_when_nothing_is_loaded(self, stubs, monkeypatch):
        stubs["monthly"] = _wr(WorkflowId.MONTHLY_PROGRESS_REPORT, [],
                               caveats=["No recognised tables."],
                               status=RESULT_UNAVAILABLE)
        wr = db.run("delay briefing", FakeRouter(0))
        assert wr.status == RESULT_UNAVAILABLE
        assert wr.substitute == "preliminary_programme_pack"
        assert "needs a programme" in wr.answer


class TestEvidenceDiscipline:
    def test_only_confirmed_events_reach_the_briefing(self, stubs, monkeypatch):
        """candidate_store.confirmed_events is the only source — candidates
        are not evidence and must never be surfaced here."""
        called = {}

        def _confirmed(corpus="", project_id=None):
            called["corpus"] = corpus
            return CONFIRMED

        monkeypatch.setattr(
            "src.delay_reports.candidate_store.confirmed_events", _confirmed)
        wr = db.run("delay briefing", FakeRouter(2))
        assert called["corpus"] == "demo"
        events = [b for b in wr.blocks
                  if b.get("title") == "Confirmed delay events"][0]
        assert events["rows"][0][1] == "2023-07-19"
        assert events["rows"][0][4] == "L1.pdf, p.3"    # sourced, not asserted


class TestBlockContract:
    def test_blocks_survive_the_response_guard(self, stubs):
        stubs["confirmed"] = CONFIRMED
        wr = db.run("delay briefing", FakeRouter(2))
        valid, dropped = validate_blocks(wr.blocks)
        assert dropped == []
        assert len(valid) == len(wr.blocks)

    def test_no_clarification_can_delete_the_briefing(self, stubs):
        stubs["confirmed"] = CONFIRMED
        wr = db.run("delay briefing", FakeRouter(2))
        assert not [b for b in wr.blocks if b["type"] == "clarification"]

    def test_a_crashing_sub_workflow_costs_only_its_section(self, stubs,
                                                            monkeypatch):
        """A briefing that dies because one section threw is worse than a
        briefing missing that section."""
        monkeypatch.setattr("src.workflows.adapters.notice_matrix.run",
                            lambda *a, **k: (_ for _ in ()).throw(
                                RuntimeError("boom")))
        stubs["confirmed"] = CONFIRMED
        wr = db.run("delay briefing", FakeRouter(2))
        text = _text(wr)
        assert "Notice compliance" not in text
        assert "Confirmed delay events" in text     # the rest survives
        assert "Progress record" in text
        assert validate_blocks(wr.blocks)[1] == []

    def test_a_crashing_router_costs_only_the_programme_sections(self, stubs):
        class Broken:
            def _programme_records(self, doc_ids=None):
                raise RuntimeError("registry down")

        stubs["confirmed"] = CONFIRMED
        wr = db.run("delay briefing", Broken())
        assert "Programme summary" not in _text(wr)
        assert "Progress record" in _text(wr)
