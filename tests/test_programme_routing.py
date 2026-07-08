"""Router-level programme tests: classification shortcut, handler
clarifications, dispatch, and response_builder mapping. No LLM, no network —
QueryRouter is never fully instantiated (heavy init); methods run on a stub.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from src.router import QueryRouter
from src.types import QueryType
from backend.services.response_builder import build_chat_response

FIXTURES = Path(__file__).parent / "fixtures" / "xer"


def _stub_router():
    return QueryRouter.__new__(QueryRouter)


def _records(n=3):
    paths = sorted(FIXTURES.glob("*.xer"))[:n]
    return [{"doc_id": p.stem, "file_name": p.name, "file_path": str(p),
             "status": "completed"} for p in paths]


@pytest.fixture(autouse=True)
def artifacts_tmp(tmp_path, monkeypatch):
    import src.programme_tools.config_paths as cp
    monkeypatch.setattr(cp, "artifacts_dir", lambda: tmp_path)
    yield


# ── _classify_programme ──────────────────────────────────────
class TestClassifyProgramme:
    def test_dcma_intent(self):
        d = _stub_router()._classify_programme("run dcma check on this xer")
        assert d is not None
        assert d.query_type == QueryType.PROGRAMME
        assert d.metadata["id"] == "programme.dcma_14_point"
        assert d.confidence >= 0.9

    def test_negative_trigger_blocks(self):
        assert _stub_router()._classify_programme(
            "who caused the delay to the milestones?") is None

    def test_plain_document_query_not_matched(self):
        assert _stub_router()._classify_programme(
            "what does the contract say about liquidated damages?") is None

    def test_agent_gate_excludes_programme(self):
        r = _stub_router()
        d = r._classify_programme("run dcma check")
        assert r._should_use_agent(d, "run dcma check") is False


# ── _handle_programme_query ──────────────────────────────────
class TestHandleProgrammeQuery:
    def test_no_files_clarification(self):
        r = _stub_router()
        with patch.object(QueryRouter, "_programme_records", return_value=[]):
            out = r._handle_programme_query("run dcma check")
        assert out["clarification"] is True
        assert "upload at least one XER" in out["answer"]
        assert out["query_type"] == "programme"

    def test_milestone_needs_two_revisions(self):
        r = _stub_router()
        with patch.object(QueryRouter, "_programme_records",
                          return_value=_records(1)):
            out = r._handle_programme_query("show me milestone movements")
        assert out.get("clarification") is True
        assert "at least 2 XER" in out["answer"]

    def test_dcma_multiple_files_asks_which(self):
        r = _stub_router()
        with patch.object(QueryRouter, "_programme_records",
                          return_value=_records(3)), \
             patch.object(QueryRouter, "_resolve_filename_hints",
                          return_value=[]):
            out = r._handle_programme_query("run dcma check")
        assert out.get("clarification") is True
        assert "Which programme" in out["answer"]
        assert "revA.xer" in out["answer"]

    def test_dcma_single_file_runs(self):
        r = _stub_router()
        with patch.object(QueryRouter, "_programme_records",
                          return_value=_records(1)), \
             patch("src.programme_tools.narrative.compose_narrative",
                   side_effect=lambda res, ctx=None, use_llm=True: res.summary) as _, \
             patch("src.router.QueryRouter._current_question",
                   side_effect=lambda q: q):
            # compose_narrative is imported inside the handler — patch at source
            out = r._handle_programme_query("run dcma check")
        assert out["query_type"] == "programme"
        art = out["programme_artifact"]
        assert art["tool_id"] == "programme.dcma_14_point"
        assert art["status"] == "complete"
        assert len(art["tables"][0]["rows"]) == 14
        assert out["answer"]  # narrative or fallback text present

    def test_milestone_runs_with_three_files(self):
        r = _stub_router()
        with patch.object(QueryRouter, "_programme_records",
                          return_value=_records(3)), \
             patch("src.programme_tools.narrative.compose_narrative",
                   side_effect=lambda res, ctx=None, use_llm=True: res.summary):
            out = r._handle_programme_query("show me milestone movements")
        art = out["programme_artifact"]
        assert art["tool_id"] == "programme.milestone_shift"
        assert any("not independently verified" in c for c in art["caveats"])

    def test_workflow_pack(self):
        r = _stub_router()
        with patch.object(QueryRouter, "_programme_records",
                          return_value=_records(3)), \
             patch("src.programme_tools.workflows.preliminary_programme_analysis"
                   ".compose_narrative",
                   side_effect=lambda res, ctx=None, use_llm=True: res.summary):
            out = r._handle_programme_query(
                "generate preliminary programme analysis report")
        pack = out["programme_artifact"]
        assert pack["workflow_id"].endswith("analysis_pack")
        section_ids = [s["section_id"] for s in pack["sections"]]
        assert "inventory" in section_ids
        assert any(s.startswith("dcma_") for s in section_ids)
        assert "milestone_shift" in section_ids
        assert "## Programme Inventory" in out["answer"]

    def test_dispatch_routes_programme(self):
        r = _stub_router()
        with patch.object(QueryRouter, "_handle_programme_query",
                          return_value={"answer": "ok", "query_type": "programme"}) as h:
            out = r._dispatch_query(QueryType.PROGRAMME, "run dcma", "run dcma", None)
        assert h.called and out["answer"] == "ok"


# ── response_builder mapping ─────────────────────────────────
class TestProgrammeResponseBuilder:
    def test_artifact_passthrough(self):
        raw = {"query_type": "programme", "answer": "narrative text",
               "sources": [],
               "programme_artifact": {"tool_id": "programme.dcma_14_point",
                                      "status": "complete", "tables": []}}
        resp = build_chat_response(raw)
        assert resp.ui_intent == "programme_result"
        assert resp.programme_artifact["tool_id"] == "programme.dcma_14_point"
        assert resp.assistant_text == "narrative text"

    def test_clarification_renders_as_plain_answer(self):
        raw = {"query_type": "programme", "clarification": True,
               "answer": "Please upload at least one XER programme file.",
               "sources": []}
        resp = build_chat_response(raw)
        assert resp.ui_intent == "answer"
        assert resp.programme_artifact is None
