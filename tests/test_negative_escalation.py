"""Negative-answer auto-escalation.

A shallow route that says "that isn't in the corpus" is re-run through the ReAct
agent when the cheap verifier judges the question answerable (WEAK, not
OFFTOPIC). The deep answer is adopted ONLY when it is better grounded — a second,
longer refusal is worse than the first, so the original is kept.

These tests target the small gate/selection methods, the same choice the existing
suite makes for _should_use_agent / _try_react_agent rather than driving the whole
of route_and_execute.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.config as cfg
from src.router import QueryRouter
from src.types import QueryType, RouterDecision


class _Trace:
    """Same shape as the stub in test_activity_and_agent.py, plus record_routing."""

    def __init__(self, route="DOCUMENT"):
        self.route = route
        self.errors = []
        self.routing = {}

    def record_error(self, e):
        self.errors.append(e)

    def record_routing(self, **kw):
        self.routing.update(kw)


class _Agent:
    def __init__(self, out):
        self.out = out
        self.kwargs = None
        self.calls = 0

    def run(self, q, doc_ids=None, **kw):
        self.calls += 1
        self.kwargs = kw
        return self.out


def _router(verdict="WEAK"):
    r = QueryRouter.__new__(QueryRouter)
    r._verify_answer = lambda q, res: verdict
    return r


def _doc():
    return RouterDecision(query_type=QueryType.DOCUMENT, confidence=0.85, reasons=[])


# A shallow refusal with no sources at all.
_NEG = {"answer": "The requested information was not found in the provided documents.",
        "sources": []}

# A grounded deep answer: real document source, substantial text.
_DEEP_GOOD = {
    "answer": "The MUDFA diversions were rescheduled section by section. " + "A" * 260,
    "query_type": "hybrid",
    "sources": [{"file_name": "mudfa.pdf", "page_number": 2}],
    "routing": {"route": "AGENT", "tools_used": ["survey_documents", "read_documents"]},
}


def _on(monkeypatch):
    monkeypatch.setattr(cfg, "ENABLE_REACT_AGENT", True)
    monkeypatch.setattr(cfg, "ENABLE_NEGATIVE_ESCALATION", True)


# ── 1. the happy path ───────────────────────────────────────────────
def test_escalates_on_weak_and_adopts_grounded_answer(monkeypatch):
    _on(monkeypatch)
    r, tr = _router(), _Trace()
    r._react_agent = _Agent(_DEEP_GOOD)

    out, verdict = r._maybe_escalate_negative("q", "q", None, _doc(), _NEG, "WEAK", tr)

    assert out is _DEEP_GOOD and verdict == "WEAK"
    assert tr.route == "DOCUMENT_ESCALATED_AGENT"
    assert tr.routing["escalation_outcome"] == "adopted"
    assert tr.routing["escalation_deep_docs"] == 1
    assert tr.routing["escalation_steps"] == 2
    # It must run on the ESCALATION budgets, not the first-class agent's — the
    # LLM budget in particular, since the shallow pass already spent most of the
    # per-query allowance and the default would cut this run short.
    assert r._react_agent.kwargs == {
        "max_iterations": cfg.ESCALATION_MAX_ITERATIONS,
        "time_budget_sec": cfg.ESCALATION_TIME_BUDGET_SEC,
        "llm_call_budget": cfg.ESCALATION_LLM_BUDGET,
    }
    assert cfg.ESCALATION_LLM_BUDGET > cfg.MAX_LLM_CALLS_PER_QUERY


# ── 2. an honest refusal stays fast ─────────────────────────────────
def test_offtopic_never_escalates(monkeypatch):
    _on(monkeypatch)
    r, tr = _router(), _Trace()
    r._react_agent = _Agent(_DEEP_GOOD)

    out, _ = r._maybe_escalate_negative("q", "q", None, _doc(), _NEG, "OFFTOPIC", tr)

    assert out is None
    assert r._react_agent.calls == 0      # no agent run, no added latency
    assert tr.route == "DOCUMENT"          # route untouched


# ── 3. "no files match" is an answer, not a failure ─────────────────
def test_file_list_never_escalates(monkeypatch):
    _on(monkeypatch)
    r = _router()
    fl = RouterDecision(query_type=QueryType.FILE_LIST, confidence=0.9, reasons=[])
    assert r._should_escalate(fl, "WEAK", _Trace(route="FILE_LIST")) is False
    data = RouterDecision(query_type=QueryType.DATA, confidence=0.9, reasons=[])
    assert r._should_escalate(data, "WEAK", _Trace(route="DATA")) is False
    # HYBRID is eligible alongside DOCUMENT.
    hyb = RouterDecision(query_type=QueryType.HYBRID, confidence=0.9, reasons=[])
    assert r._should_escalate(hyb, "WEAK", _Trace(route="HYBRID")) is True


# ── 4. no double run ────────────────────────────────────────────────
def test_never_escalates_a_run_that_was_already_the_agent(monkeypatch):
    _on(monkeypatch)
    r = _router()
    assert r._should_escalate(_doc(), "WEAK", _Trace(route="AGENT")) is False
    assert r._should_escalate(_doc(), "WEAK", _Trace(route="AGENT_FAILED_FALLBACK")) is False
    assert r._should_escalate(_doc(), "WEAK", _Trace(route="DOCUMENT_ESCALATED_KEPT")) is False
    assert r._should_escalate(_doc(), "WEAK", _Trace(route="DOCUMENT_ESCALATED_AGENT")) is False


# ── 5. escalation must never make the answer worse ──────────────────
def test_keeps_the_original_refusal_unless_the_deep_pass_is_better():
    r = _router()
    # nothing found at all
    assert r._pick_escalated(_NEG, {"answer": "B" * 300, "sources": []}) is None
    # a longer refusal — and short enough that response_builder would strip its
    # citations, so adopting it would trade a clean "not found" for a vaguer one
    assert r._pick_escalated(_NEG, {
        "answer": "I could not find any document that mentions this topic.",
        "sources": [{"file_name": "x.pdf", "page_number": 1}]}) is None
    # too thin to be an improvement
    assert r._pick_escalated(_NEG, {
        "answer": "Yes.", "sources": [{"file_name": "x.pdf"}]}) is None
    # Excel tables only — no document was actually rescued
    assert r._pick_escalated(_NEG, {
        "answer": "C" * 300,
        "sources": [{"file_name": "boq.xlsx", "type": "structured_data"}]}) is None
    # the one case worth adopting
    assert r._pick_escalated(_NEG, _DEEP_GOOD) is _DEEP_GOOD


def test_agent_failure_keeps_the_first_pass_answer(monkeypatch):
    _on(monkeypatch)

    class _Boom:
        def run(self, q, doc_ids=None, **kw):
            raise RuntimeError("agent broke")

    r, tr = _router(), _Trace()
    r._react_agent = _Boom()

    out, _ = r._maybe_escalate_negative("q", "q", None, _doc(), _NEG, "WEAK", tr)

    assert out is None                                   # caller keeps its answer
    assert tr.route == "DOCUMENT_ESCALATION_FAILED"      # and the failure is visible
    assert tr.errors and "agent broke" in tr.errors[0]


# ── 6. switches ─────────────────────────────────────────────────────
def test_kill_switch_and_agent_disabled(monkeypatch):
    r, tr = _router(), _Trace()
    monkeypatch.setattr(cfg, "ENABLE_REACT_AGENT", True)
    monkeypatch.setattr(cfg, "ENABLE_NEGATIVE_ESCALATION", False)
    assert r._should_escalate(_doc(), "WEAK", tr) is False
    monkeypatch.setattr(cfg, "ENABLE_NEGATIVE_ESCALATION", True)
    monkeypatch.setattr(cfg, "ENABLE_REACT_AGENT", False)
    assert r._should_escalate(_doc(), "WEAK", tr) is False


# ── 7. the structured-data mask ─────────────────────────────────────
def test_excel_only_sources_do_not_hide_a_negative(monkeypatch):
    """_handle_document_query attaches related Excel tables even when retrieval
    returned nothing, so _verify_answer short-circuits to a free OK and the
    negative is never questioned. The gate must spend the lite call it skipped —
    exactly once, on a document-only view — and escalate on the result."""
    _on(monkeypatch)
    r, tr = _router(), _Trace()
    calls = {"n": 0}

    def _verify(q, res):
        calls["n"] += 1
        assert res["sources"] == [], "re-check must judge the answer without the Excel sources"
        return "WEAK"

    r._verify_answer = _verify
    r._react_agent = _Agent(_DEEP_GOOD)
    masked = {"answer": "That information was not found in the provided documents.",
              "sources": [{"file_name": "boq.xlsx", "type": "structured_data"}]}

    out, verdict = r._maybe_escalate_negative("q", "q", None, _doc(), masked, "OK", tr)

    assert out is _DEEP_GOOD and verdict == "WEAK"
    assert calls["n"] == 1, "at most one extra lite call per query"


def test_strong_answer_costs_nothing_extra(monkeypatch):
    """A grounded answer must not reach the gate's LLM branch at all."""
    _on(monkeypatch)
    r, tr = _router(), _Trace()

    def _never(q, res):
        raise AssertionError("a strong answer must not spend a verify call")

    r._verify_answer = _never
    r._react_agent = _Agent(_DEEP_GOOD)
    strong = {"answer": "The contract sets out the payment terms in clause 60." * 4,
              "sources": [{"file_name": "contract.pdf", "page_number": 3}]}

    out, verdict = r._maybe_escalate_negative("q", "q", None, _doc(), strong, "OK", tr)

    assert out is None and verdict == "OK"
    assert r._react_agent.calls == 0


# ── 8. the wiring, end to end through route_and_execute ─────────────
def _wire(monkeypatch, router, dispatch_result):
    """Stub route_and_execute's collaborators down to the escalation block."""
    import src.telemetry as tel

    monkeypatch.setattr(tel, "start_trace", lambda q: _Trace(route=None))
    monkeypatch.setattr(tel, "finish_trace", lambda: None)

    class _Jargon:
        def expand_query(self, q):
            return q

    class _Data:
        def list_tables(self):
            return []          # no tables → the DOCUMENT→DATA fallback is skipped

    router._jargon = _Jargon()          # `jargon` is a lazy property over this
    router.data_analyzer = _Data()
    router._is_greeting = lambda q: False
    router._is_complex_query = lambda q: False
    router.classify_query = lambda q, mode=None: _doc()
    router._should_use_agent = lambda d, q: False
    router._dispatch_query = lambda qt, q, exp, ids: dispatch_result


def test_route_and_execute_returns_the_escalated_answer(monkeypatch):
    _on(monkeypatch)
    r = _router()
    r._react_agent = _Agent(_DEEP_GOOD)
    _wire(monkeypatch, r, _NEG)

    out = r.route_and_execute("was a completion notice ever issued?")

    assert out["answer"] == _DEEP_GOOD["answer"]
    assert out["verify_verdict"] == "WEAK"
    # the agent's own routing survives, annotated rather than overwritten, but
    # the route is marked so an escalation is distinguishable from a first-class
    # agent run in the API response (response_builder reads routing["route"])
    assert out["routing"]["route"] == "ESCALATED_AGENT"
    assert out["routing"]["escalated"] is True
    assert out["routing"]["escalated_from"] == "document"
    assert out["routing"]["tools_used"] == ["survey_documents", "read_documents"]
    assert any("escalated" in x for x in out["routing"]["reasons"])
    # query_type stays "hybrid" so response_builder does not strip the citations
    # it just went and found
    assert out["query_type"] == "hybrid"


def test_route_and_execute_keeps_the_refusal_when_the_deep_pass_finds_nothing(monkeypatch):
    _on(monkeypatch)
    r = _router()
    r._react_agent = _Agent({"answer": "Still nothing.", "sources": [],
                             "routing": {"route": "AGENT", "tools_used": ["survey_documents"]}})
    _wire(monkeypatch, r, _NEG)

    out = r.route_and_execute("was a completion notice ever issued?")

    assert out["answer"] == _NEG["answer"]          # the original, honest refusal
    assert out["routing"]["decision"] == "document"  # normal shallow metadata
    assert out["verify_verdict"] == "WEAK"


def test_route_and_execute_is_unchanged_for_a_strong_answer(monkeypatch):
    _on(monkeypatch)
    r = _router(verdict="OK")
    r._react_agent = _Agent(_DEEP_GOOD)
    strong = {"answer": "Clause 60 sets the payment terms." * 6,
              "sources": [{"file_name": "contract.pdf", "page_number": 3}]}
    _wire(monkeypatch, r, strong)

    out = r.route_and_execute("what are the payment terms?")

    assert out["answer"] == strong["answer"]
    assert r._react_agent.calls == 0
    assert out["routing"]["decision"] == "document"


def test_verify_looks_weak_matches_the_verifier_shortcut():
    """The extracted predicate must stay identical to _verify_answer's free
    early-return, or the gate's 'did verify cost anything?' question is wrong."""
    assert QueryRouter._verify_looks_weak("not found anywhere", []) is True
    assert QueryRouter._verify_looks_weak("", []) is True
    assert QueryRouter._verify_looks_weak("x" * 200, []) is False       # long, no negative
    # any source at all short-circuits it — that is the mask test 7 covers
    assert QueryRouter._verify_looks_weak("not found", [{"file_name": "a.xlsx"}]) is False
