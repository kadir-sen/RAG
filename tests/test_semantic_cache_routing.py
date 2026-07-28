"""Semantic-cache classification: a cache hit must actually be USED.

Regression for a bug where every semantic-cache hit threw away the route it had
just found. `resp` is only bound on the LLM branch, but the usage block read
`resp.usage` unconditionally → UnboundLocalError → swallowed by the enclosing
except → `_classify_llm_rich` returned None → `classify_query` fell through to
the keyword safety net at confidence 0.5. Net effect: the cache cost an
embedding and bought nothing, and a paraphrase of a working question routed
worse than the original.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.router import QueryRouter
from src.types import QueryType


def _router(monkeypatch):
    """A router with just enough wired up to reach the cache branch."""
    r = QueryRouter.__new__(QueryRouter)
    monkeypatch.setattr(QueryRouter, "_get_classification_context",
                        lambda self: ("files: a.pdf", "tables: none"), raising=False)
    monkeypatch.setattr(QueryRouter, "_get_topic_inventory",
                        lambda self: "topics: delays", raising=False)
    return r


def test_semantic_cache_hit_is_used_not_discarded(monkeypatch):
    """The whole point of the fix: a hit returns a real decision, not None."""
    import src.semantic_cache as sc
    monkeypatch.setattr(sc, "embed_query", lambda q: [0.1, 0.2])
    monkeypatch.setattr(sc, "lookup", lambda sig, vec, threshold=0.97: "FILE_LIST")

    # If the cache branch is taken, no LLM call may happen at all.
    import src.llm_client as llm
    def _boom(*a, **k):
        raise AssertionError("cache hit must not call the LLM")
    monkeypatch.setattr(llm, "generate_text", _boom)

    decision = _router(monkeypatch)._classify_llm_rich("which files mention delays?")

    assert decision is not None, "cache hit was discarded (the original bug)"
    assert decision.query_type == QueryType.FILE_LIST
    assert decision.confidence == 0.85          # not the 0.5 safety-net default
    # No LLM was called, so nothing may be billed as one.
    assert decision.used_llm is False
    assert decision.llm_usage is None
    assert any("semantic cache" in r for r in decision.reasons)


def test_cache_miss_still_bills_the_llm_call(monkeypatch):
    """The miss path is unchanged: real usage still flows into the trace."""
    from src.llm_client import LLMResponse
    from src.types import LLMUsage
    import src.semantic_cache as sc
    import src.llm_client as llm

    monkeypatch.setattr(sc, "embed_query", lambda q: [0.1, 0.2])
    monkeypatch.setattr(sc, "lookup", lambda sig, vec, threshold=0.97: None)
    monkeypatch.setattr(sc, "put", lambda sig, vec, val: None)
    monkeypatch.setattr(llm, "generate_text", lambda p, **k: LLMResponse(
        text="DOCUMENT",
        usage=LLMUsage(prompt_tokens=12, completion_tokens=3,
                       cost_estimate=0.5, provider="gemini"),
    ))

    decision = _router(monkeypatch)._classify_llm_rich("what does the contract say?")

    assert decision is not None
    assert decision.query_type == QueryType.DOCUMENT
    assert decision.used_llm is True
    assert decision.llm_usage == {"prompt_tokens": 12, "completion_tokens": 3, "cost": 0.5}


def test_cache_backend_failure_falls_through_to_the_llm(monkeypatch):
    """An unavailable cache must degrade to a normal LLM classification, not None."""
    from src.llm_client import LLMResponse
    from src.types import LLMUsage
    import src.semantic_cache as sc
    import src.llm_client as llm

    def _down(*a, **k):
        raise RuntimeError("cache backend down")

    monkeypatch.setattr(sc, "embed_query", _down)
    monkeypatch.setattr(llm, "generate_text", lambda p, **k: LLMResponse(
        text="DATA", usage=LLMUsage(provider="gemini")))

    decision = _router(monkeypatch)._classify_llm_rich("total hours by trade")

    assert decision is not None and decision.query_type == QueryType.DATA
    assert decision.used_llm is True
