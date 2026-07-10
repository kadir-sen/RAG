"""Workflow executor — delegation, input summary, caveats, clarifications."""

from pathlib import Path
from unittest.mock import patch

import pytest

from src.router import QueryRouter
from src.workflows import plan, run_workflow
from src.workflows.executor import run_workflow as _run
from src.workflows.types import WorkflowId

FIXTURES = Path(__file__).parent / "fixtures" / "xer"


def _records(n=3):
    paths = sorted(FIXTURES.glob("*.xer"))[:n]
    return [{"doc_id": p.stem, "file_name": p.name, "file_path": str(p),
             "status": "completed"} for p in paths]


def _stub_router(records=None):
    r = QueryRouter.__new__(QueryRouter)
    recs = records if records is not None else _records()
    r._programme_records = lambda doc_ids=None: recs
    return r


@pytest.fixture(autouse=True)
def artifacts_tmp(tmp_path, monkeypatch):
    import src.programme_tools.config_paths as cp
    monkeypatch.setattr(cp, "artifacts_dir", lambda: tmp_path)
    yield


def _types(wr):
    return [b["type"] for b in wr.blocks]


# ── planned / unavailable ────────────────────────────────────

def test_planned_returns_structured_substitute_not_error():
    # internal_eot_roadmap uses the generic planned response (notice matrix is
    # now prerequisite-aware and tested separately).
    wp = plan("create internal eot roadmap")
    wr = run_workflow(wp, "create internal eot roadmap", _stub_router())
    assert wr.status == "unavailable"
    assert _types(wr) == ["markdown_text"]          # not clarification, not error
    assert "clarification" not in _types(wr)
    assert wr.substitute == WorkflowId.PRELIMINARY_PROGRAMME_PACK.value
    assert "planned" in wr.answer.lower()


def test_planned_does_not_crash_without_router():
    wp = plan("create internal eot roadmap")
    wr = run_workflow(wp, "create internal eot roadmap", None)
    assert wr.status == "unavailable"


# ── clarifications / missing inputs ──────────────────────────

def test_missing_xer_returns_clarification():
    wp = plan("what programme files are available")
    wr = run_workflow(wp, "what programme files are available",
                      _stub_router([]))
    assert wr.status == "clarification"
    assert _types(wr) == ["clarification"]


def test_one_xer_milestone_requires_two():
    wp = plan("show milestone movements as a chart")
    wr = run_workflow(wp, "show milestone movements as a chart",
                      _stub_router(_records(1)))
    assert wr.status == "clarification"
    assert "two" in wr.answer.lower() or "2" in wr.answer


# ── available delegation ─────────────────────────────────────

def test_programme_inventory_end_to_end():
    wp = plan("what programme files are available")
    wr = run_workflow(wp, "what programme files are available", _stub_router())
    assert wr.status in ("success", "partial")
    t = _types(wr)
    assert t[0] == "markdown_text" and "input resolution" in wr.blocks[0]["text"].lower()
    assert "data_table" in t
    assert "validation_status" in t


def test_milestone_chart_end_to_end_llm_disabled():
    # compose_narrative stubbed → deterministic; workflow still produces blocks.
    with patch("src.programme_tools.narrative.compose_narrative",
               side_effect=lambda res, ctx=None, use_llm=True: res.summary):
        wp = plan("show milestone movements as a chart")
        wr = run_workflow(wp, "show milestone movements as a chart",
                          _stub_router())
    assert wr.status in ("success", "partial")
    t = _types(wr)
    assert t[0] == "markdown_text"                      # input resolution first
    assert "chart" in t and "data_table" in t
    assert "validation_status" in t
    # movement≠causation caveat injected by the workflow layer
    assert any("causation" in c.lower() for c in wr.caveats)


def test_dcma_latest_injects_health_caveat():
    from src.orchestration.resolver import ResolveOutcome
    recs = _records(3)
    picked = {"doc_id": recs[-1]["doc_id"], "file_name": recs[-1]["file_name"],
              "file_path": recs[-1]["file_path"],
              "meta": {"data_date": "2026-01-01"}}
    ok = ResolveOutcome(resolved={"current_xer": picked})
    with patch("src.orchestration.resolver.resolve_xer", return_value=ok), \
         patch("src.programme_tools.narrative.compose_narrative",
               side_effect=lambda res, ctx=None, use_llm=True: res.summary):
        wp = plan("run dcma on the latest update programme")
        wr = run_workflow(wp, "run dcma on the latest update programme",
                          _stub_router())
    assert wr.status in ("success", "partial")
    assert any(b["type"] == "data_table" and len(b["rows"]) == 14
               for b in wr.blocks)
    assert any("dcma is a schedule-health check" in c.lower()
               for c in wr.caveats)
    assert wr.blocks[0]["type"] == "markdown_text"       # input resolution


def test_analyst_review_propagates_for_chronology():
    out = {"answer": "6.1.1 On 2024-03-01 the contractor…",
           "query_type": "delay_report",
           "programme_artifact": {"tables": [{"title": "Chronology",
                                              "columns": ["Ref", "Event"],
                                              "rows": [["6.1.1", "x"]]}],
                                  "caveats": [], "requires_analyst_review": True,
                                  "validation": {}},
           "sources": []}
    with patch("src.delay_reports.run_event_chronology", return_value=out):
        wp = plan("delayed blockwork's chronology in 6.1 format")
        wr = run_workflow(wp, "delayed blockwork's chronology in 6.1 format",
                          _stub_router())
    assert wr.analyst_review_required is True
    assert any(b["type"] == "validation_status"
               and b["requires_analyst_review"] for b in wr.blocks)
