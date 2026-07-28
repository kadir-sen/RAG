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


# ── 7. the shapes measured in production ────────────────────────────
# Answers taken verbatim from the deployed system. The first two are confirmed
# false negatives: asked again through the deep path, the corpus turned out to
# hold five documents naming "Phase 1b — Roseburn to Granton" and three
# describing geotechnical boreholes.
_PHASE_1B = {
    "query_type": "document",
    "answer": ('Please provide a specific question regarding "Phase 1b". The provided '
               'document excerpts do not contain information explicitly labeled '
               '"Phase 1b". They refer to "Phase 1" and "Phase 2" in the context of '
               '"Servicing Access Strategy Existing Restrictions" (CEC01526804.pdf, '
               'p.2; CEC01533381.pdf, p.5) and "All Underpass - Phase 2" '
               '(BFB00112198.pdf, p.24).'),
    "sources": [{"file_name": f"CEC0152680{i}.pdf", "page_number": i} for i in range(1, 11)],
}
_BOREHOLES = {
    "query_type": "document",
    "answer": ("I am sorry, but the provided documents do not contain information about "
               "geotechnical borehole logs or SPT values recorded near Haymarket."),
    "sources": [{"file_name": "CEC01511679.pdf", "page_number": 4}],
}


def test_a_denial_that_cites_documents_still_escalates(monkeypatch):
    """The case that made this redesign necessary.

    The first version of the gate required zero document citations, so it would
    have let this through untouched: 351 characters, ten citations, reading as a
    grounded answer — and wrong. The verdict is now the whole gate.
    """
    _on(monkeypatch)
    r, tr = _router(), _Trace()
    r._react_agent = _Agent(_DEEP_GOOD)

    out, _ = r._maybe_escalate_negative("Who signed the certificate of practical "
                                        "completion for Phase 1b?", "q", None,
                                        _doc(), _PHASE_1B, "WEAK", tr)

    assert out is _DEEP_GOOD
    assert tr.route == "DOCUMENT_ESCALATED_AGENT"


def test_the_measured_refusals_are_recognised_as_denials():
    """Neither of the two old pattern lists matched these. One list now, and it
    does — which is what makes the router's contradiction guard and the response
    builder's citation-stripping work on real answers rather than tidy ones."""
    from src.answer_signals import denies_corpus

    assert denies_corpus(_PHASE_1B["answer"]) is True
    assert denies_corpus(_BOREHOLES["answer"]) is True
    assert denies_corpus("The provided document excerpts do not contain any "
                         "information regarding 'preheat temperature'.") is True
    # …and a substantive answer that merely contains a negation is NOT a denial.
    assert denies_corpus("The contract does not contain a termination clause; "
                         "clause 60 governs payment instead.") is False
    assert denies_corpus("Yes. The completion date moved from 2011 to 2014.") is False
    assert denies_corpus("") is False


def test_a_nuanced_refusal_keeps_its_explanation():
    """Broadening the shared patterns must not let the contradiction guard
    flatten a refusal that says what it DID find into a bare document count."""
    r = QueryRouter.__new__(QueryRouter)
    # bare — safe to replace / strip citations from
    assert r._is_bare_denial("") is True
    assert r._is_bare_denial("The documents do not contain that information.") is True
    # nuanced — 351 chars of real content about what was found; must survive
    assert r._is_bare_denial(_PHASE_1B["answer"]) is False
    assert QueryRouter._looks_like_no_document_answer(_PHASE_1B["answer"]) is True


_ANSWERED = {
    "query_type": "document",
    "answer": ("The delay to the construction of the depot was caused by a water main "
               "restricting site access from 01/08/08 until 18/02/09, and by outstanding "
               "MUDFA works in the same area." + " Further detail follows." * 6),
    "sources": [{"file_name": f"CEC0044340{i}.pdf", "page_number": i} for i in range(1, 10)],
}


def test_only_a_denial_is_judged(monkeypatch):
    """Both halves of the gate, and each was learned the expensive way.

    A denial WITH citations must reach the judge — that is the shape of the real
    false negatives. An answer that actually answers must not: judging those had
    the judge calling them incomplete, and every one cost a ~45s deep pass that
    was then discarded. Measured on production: 21s → 125s on a correct answer.
    """
    r = QueryRouter.__new__(QueryRouter)
    spent = {"n": 0}

    import src.llm_client as llm
    from src.llm_client import LLMResponse
    from src.types import LLMUsage

    def _judge(prompt, **k):
        spent["n"] += 1
        assert "weak/empty draft" not in prompt, "the judge must not be told the verdict"
        return LLMResponse(text="INCOMPLETE", usage=LLMUsage(provider="gemini"))

    monkeypatch.setattr(llm, "generate_text", _judge)

    # denies the corpus while citing ten documents → judged
    assert r._verify_answer("q", _PHASE_1B) == "WEAK"
    assert spent["n"] == 1

    # answers the question with nine citations → not judged, costs nothing
    assert r._verify_answer("q", _ANSWERED) == "OK"
    assert spent["n"] == 1, "a substantive answer must not spend a verify call"

    # the same denial on a DATA route takes the old free path
    assert r._verify_answer("q", dict(_PHASE_1B, query_type="data")) == "OK"
    assert spent["n"] == 1


def test_reads_as_denial():
    r = QueryRouter.__new__(QueryRouter)
    assert r._reads_as_denial(_PHASE_1B) is True          # cited, but denies
    assert r._reads_as_denial(_BOREHOLES) is True
    assert r._reads_as_denial({"answer": "x", "sources": []}) is True   # cites nothing
    assert r._reads_as_denial(_ANSWERED) is False
    # Excel-only citations are not documents, so this is still a denial
    assert r._reads_as_denial({
        "answer": "Here are the totals." * 20,
        "sources": [{"file_name": "boq.xlsx", "type": "structured_data"}]}) is True


def test_verdict_tokens_map_both_old_and_new(monkeypatch):
    """COMPLETE must not be read as INCOMPLETE, and the previous Turkish tokens
    still map — a cached or drifting response must never turn an out-of-corpus
    question into a 45-second search."""
    r = QueryRouter.__new__(QueryRouter)
    import src.llm_client as llm
    from src.llm_client import LLMResponse
    from src.types import LLMUsage

    for token, expected in [("COMPLETE", "OK"), ("INCOMPLETE", "WEAK"),
                            ("OUTSIDE", "OFFTOPIC"), ("EKSIK", "WEAK"),
                            ("KONU_DISI", "OFFTOPIC"), ("TAMAM", "OK")]:
        monkeypatch.setattr(llm, "generate_text", lambda p, _t=token, **k: LLMResponse(
            text=_t, usage=LLMUsage(provider="gemini")))
        assert r._verify_answer("q", _PHASE_1B) == expected, token


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
