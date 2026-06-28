"""Tests for the live activity feed store, retrieve-only planner step, and the
bounded ReAct agent (fail-soft + retrieve-only tools)."""
import json
from unittest.mock import MagicMock

from src.types import LLMUsage
from src.llm_client import LLMResponse


# ── query progress store ────────────────────────────────────────────
def test_query_progress_start_add_finish():
    from backend.tasks.query_progress import QueryProgress
    qp = QueryProgress()
    qp.start("r1")
    qp.add("r1", "thinking", "thinking…")
    qp.add("r1", "reading", "reading a.pdf", "p.1")
    qp.finish("r1")
    a = qp.get("r1")
    assert [s.kind for s in a.steps] == ["thinking", "reading"]
    assert [s.seq for s in a.steps] == [0, 1]
    assert a.done is True


def test_query_progress_step_cap():
    from backend.tasks.query_progress import QueryProgress, _STEP_CAP
    qp = QueryProgress()
    qp.start("r")
    for i in range(_STEP_CAP + 25):
        qp.add("r", "thinking", f"s{i}")
    assert len(qp.get("r").steps) == _STEP_CAP


def test_report_step_noop_without_request():
    from backend.tasks.query_progress import query_request_var, report_step
    query_request_var.set("")
    report_step("thinking", "should be dropped")  # must not raise / must not create


# ── retrieve-only planner document step ─────────────────────────────
def test_document_step_retrieve_only_builds_excerpts():
    from src.query_planner import PlanExecutor
    ex = PlanExecutor.__new__(PlanExecutor)
    ex._document_rag = MagicMock()
    ex._document_rag.query.return_value = {
        "answer": "",
        "sources": [{"file_name": "a.pdf", "page_number": 2, "text_snippet": "hello clause"}],
    }
    r = ex._execute_document_step("q", doc_ids=None, synthesize=False)
    ex._document_rag.query.assert_called_once_with("q", doc_ids=None, synthesize=False)
    # answer rebuilt deterministically from sources (no LLM) so COMBINE has text
    assert "a.pdf" in r["answer"] and "hello clause" in r["answer"]


# ── ReAct agent ─────────────────────────────────────────────────────
class _FakeRAG:
    def __init__(self):
        self.synth_flags = []

    def query(self, q, doc_ids=None, synthesize=True):
        self.synth_flags.append(synthesize)
        return {"answer": "", "sources": [
            {"file_name": "a.pdf", "page_number": 1, "text_snippet": "availability clause"},
        ]}


class _FakeRouter:
    def __init__(self):
        self.document_rag = _FakeRAG()

    def _handle_data_query(self, q, doc_ids=None):
        return {"answer": "120 hours", "sources": [],
                "sql": "SELECT 1", "result_data": [[120]], "result_columns": ["hours"]}

    def _handle_timeline_query(self, q):
        return {"answer": "timeline", "sources": []}

    def _handle_file_list_query(self, q, doc_ids=None):
        return {"answer": "files", "sources": []}


def _resp(d):
    return LLMResponse(text=json.dumps(d),
                       usage=LLMUsage(prompt_tokens=1, completion_tokens=1, provider="gemini"),
                       raw=d)


def test_react_agent_finish_uses_retrieve_only(monkeypatch):
    import src.react_agent as ra
    seq = iter([
        {"thought": "search docs", "action": "document_search", "action_input": "availability clause"},
        {"thought": "have enough", "action": "finish", "action_input": "Final answer."},
    ])
    monkeypatch.setattr(ra.llm_client, "generate_json", lambda p, **k: _resp(next(seq)))
    router = _FakeRouter()
    res = ra.ReActAgent(router).run("compare clause with hours")
    assert res["answer"] == "Final answer."
    assert res["routing"]["decision"] == "agent"
    # the document tool must run retrieve-only (no double synthesis)
    assert router.document_rag.synth_flags == [False]
    assert len(res["sources"]) == 1


def test_react_agent_failsoft_never_drops_answer(monkeypatch):
    import src.react_agent as ra

    def boom(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(ra.llm_client, "generate_json", boom)
    monkeypatch.setattr(ra.llm_client, "generate_text",
                        lambda p, **k: LLMResponse(text="SYNTH", usage=LLMUsage(provider="gemini")))
    res = ra.ReActAgent(_FakeRouter()).run("complex q")
    # decide failed → finish('') → final synthesis path → still a non-empty answer
    assert isinstance(res["answer"], str) and res["answer"].strip()
