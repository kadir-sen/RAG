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


def test_agent_read_memory_filter_new():
    from src.react_agent import ReActAgent
    seen = set()
    srcs = [{"file_name": "a.pdf", "page_number": 1},
            {"file_name": "a.pdf", "page_number": 1},  # dup
            {"file_name": "b.pdf", "page_number": 2}]
    fresh1 = ReActAgent._filter_new(srcs, seen)
    assert [(s["file_name"], s["page_number"]) for s in fresh1] == [("a.pdf", 1), ("b.pdf", 2)]
    # second pass over the same docs -> nothing new (read-memory)
    assert ReActAgent._filter_new(srcs, seen) == []


class _FakeRAG2:
    def query(self, q, top_k=10, doc_ids=None, file_names=None, payload_filters=None, synthesize=True):
        return {"answer": "", "sources": [
            {"doc_id": "d1", "file_name": "contract.pdf", "page_number": 1,
             "highlight_text": "agreement between council and contractor", "text_snippet": "x"},
            {"doc_id": "d2", "file_name": "audit.pdf", "page_number": 3,
             "highlight_text": "cost estimates need scrutiny", "text_snippet": "y"},
            {"doc_id": "d1", "file_name": "contract.pdf", "page_number": 2,
             "highlight_text": "clause 80", "text_snippet": "z"},
        ]}


class _RouterSurvey:
    def __init__(self):
        self.document_rag = _FakeRAG2()


def test_metadata_survey_returns_metadata_no_fulltext():
    from src.react_agent import ReActAgent
    rows, chunks = ReActAgent(_RouterSurvey())._metadata_survey("cost", None)
    assert [r["file_name"] for r in rows] == ["contract.pdf", "audit.pdf"]  # deduped by file
    assert "agreement" in rows[0]["gist"]  # graceful fallback to highlight (no enrichment)
    assert set(chunks) == {"contract.pdf", "audit.pdf"} and len(chunks["contract.pdf"]) == 2


def test_survey_caches_then_read_serves_from_cache_with_memory():
    from src.react_agent import ReActAgent
    ag = ReActAgent(_RouterSurvey())
    seen, cache = set(), {}
    obs, srcs, _ = ag._run_tool("survey_documents", "cost", None, seen, cache)
    assert srcs == [] and "contract.pdf" in obs and seen == set()  # survey = metadata only
    assert cache and "contract.pdf" in cache                        # chunks stashed
    obs2, srcs2, _ = ag._run_tool("read_documents", "contract.pdf, audit.pdf", None, seen, cache)
    assert len(srcs2) == 3 and len(seen) == 3   # served from cache, fills read-memory
    obs3, srcs3, _ = ag._run_tool("read_documents", "contract.pdf", None, seen, cache)
    assert srcs3 == []                          # re-read blocked by read-memory


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


# ── agent observability + stuck-loop (Faz 1a/1f) ────────────────────
def test_react_agent_routing_marks_route_and_tools(monkeypatch):
    """run() must expose route='AGENT' + tools_used so the agent is distinguishable
    from the hybrid executor in the response/telemetry (both share query_type)."""
    import src.react_agent as ra
    seq = iter([
        {"action": "document_search", "action_input": "x"},
        {"action": "finish", "action_input": "done"},
    ])
    monkeypatch.setattr(ra.llm_client, "generate_json", lambda p, **k: _resp(next(seq)))
    res = ra.ReActAgent(_FakeRouter()).run("q")
    assert res["routing"]["route"] == "AGENT"
    assert res["routing"]["tools_used"] == ["document_search"]


def test_react_agent_stuck_loop_breaks_early(monkeypatch):
    """The LLM repeating the identical action must not burn all iterations — the
    agent breaks and synthesizes instead of looping."""
    import src.react_agent as ra
    calls = {"n": 0}

    def same_action(p, **k):
        calls["n"] += 1
        return _resp({"action": "document_search", "action_input": "same"})

    monkeypatch.setattr(ra.llm_client, "generate_json", same_action)
    monkeypatch.setattr(ra.llm_client, "generate_text",
                        lambda p, **k: LLMResponse(text="SYNTH", usage=LLMUsage(provider="gemini")))
    res = ra.ReActAgent(_FakeRouter()).run("q")
    # 1st decide runs the tool; 2nd decide repeats → break before REACT_MAX_ITERATIONS(5)
    assert calls["n"] <= 2
    assert res["answer"].strip()


# ── router agent gate + visible fallback (Faz 1b/1d) ────────────────
class _Trace:
    def __init__(self):
        self.route = None
        self.errors = []

    def record_error(self, e):
        self.errors.append(e)


def test_should_use_agent_gates():
    from src.router import QueryRouter
    from src.types import QueryType, RouterDecision
    r = QueryRouter.__new__(QueryRouter)
    hybrid = RouterDecision(query_type=QueryType.HYBRID, confidence=0.9, reasons=[])
    assert r._should_use_agent(hybrid, "anything") is True
    strong_doc = RouterDecision(query_type=QueryType.DOCUMENT, confidence=0.9, reasons=[])
    assert r._should_use_agent(strong_doc, "what is clause 5?") is False
    low_multi = RouterDecision(query_type=QueryType.DOCUMENT, confidence=0.4, reasons=[])
    assert r._should_use_agent(low_multi, "what is x? and what is y?") is True


def test_try_react_agent_disabled_returns_none(monkeypatch):
    from src.router import QueryRouter
    import src.config as cfg
    monkeypatch.setattr(cfg, "ENABLE_REACT_AGENT", False)
    r = QueryRouter.__new__(QueryRouter)
    tr = _Trace()
    assert r._try_react_agent("q", None, tr, "x") is None


def test_try_react_agent_failure_is_visible(monkeypatch):
    """Agent raising must NOT silently look like a normal hybrid — the trace route
    records AGENT_FAILED_FALLBACK and the error is recorded; caller gets None."""
    from src.router import QueryRouter
    import src.config as cfg
    monkeypatch.setattr(cfg, "ENABLE_REACT_AGENT", True)
    r = QueryRouter.__new__(QueryRouter)

    class _Boom:
        def run(self, q, doc_ids=None):
            raise RuntimeError("agent broke")

    r._react_agent = _Boom()
    tr = _Trace()
    out = r._try_react_agent("q", None, tr, "x")
    assert out is None
    assert tr.route == "AGENT_FAILED_FALLBACK"
    assert tr.errors and "agent broke" in tr.errors[0]


def test_try_react_agent_success_marks_route(monkeypatch):
    from src.router import QueryRouter
    import src.config as cfg
    monkeypatch.setattr(cfg, "ENABLE_REACT_AGENT", True)
    r = QueryRouter.__new__(QueryRouter)

    class _Ok:
        def run(self, q, doc_ids=None):
            return {"answer": "A", "sources": [], "routing": {"route": "AGENT"}}

    r._react_agent = _Ok()
    tr = _Trace()
    out = r._try_react_agent("q", None, tr, "x")
    assert out and out["answer"] == "A" and tr.route == "AGENT"
