"""Faz 3 — data flywheel birim testleri (network/LLM gerektirmez).

feedback_store + golden_set + flywheel'in doküman-gerektirmeyen parçaları
(routing few-shot öğrenme, jargon öğrenme, golden set, salient terms).
"""
import os

import pytest

import src.feedback_store as fb
import src.flywheel as fw
import src.golden_set as gs


@pytest.fixture(autouse=True)
def clean_stores():
    for p in (fb.FEEDBACK_FILE, fw.ROUTING_EXAMPLES_FILE, gs.GOLDEN_FILE):
        if p.exists():
            p.unlink()
    yield
    for p in (fb.FEEDBACK_FILE, fw.ROUTING_EXAMPLES_FILE, gs.GOLDEN_FILE):
        if p.exists():
            p.unlink()


class TestFeedbackStore:
    def test_record_and_summary(self):
        fb.record_feedback({"username": "u", "message_id": "a", "vote": "up", "route": "data", "question": "q1"})
        fb.record_feedback({"username": "u", "message_id": "b", "vote": "down", "route": "document", "question": "q2"})
        s = fb.summary()
        assert s["total"] == 2 and s["up"] == 1 and s["down"] == 1
        assert s["by_route"]["data"]["up"] == 1
        assert s["by_route"]["document"]["down"] == 1


class TestRoutingLearning:
    def test_learn_and_dedupe(self):
        fb.record_feedback({"vote": "up", "route": "data", "question": "how many fixers on Block A"})
        feedback = fb.load_feedback()
        assert fw._learn_routing(feedback) == 1
        assert fw._learn_routing(feedback) == 0  # idempotent
        ex = fw.get_learned_routing_examples()
        assert ex and ex[0]["route"] == "data"

    def test_downvote_not_learned_as_route(self):
        fb.record_feedback({"vote": "down", "route": "data", "question": "wrong route q"})
        assert fw._learn_routing(fb.load_feedback()) == 0


class TestJargonLearning:
    def test_correction_becomes_custom_term(self):
        fb.record_feedback({"vote": "down", "route": "data", "question": "q",
                            "correction": "ZQX = Zone Quality Index"})
        n = fw._learn_jargon(fb.load_feedback())
        from src.jargon_manager import get_jargon_manager
        jm = get_jargon_manager()
        try:
            assert n == 1
            assert "Zone Quality Index" in jm.expand_query("ZQX")
        finally:
            try:
                jm.remove_custom_term("ZQX")
            except Exception:
                pass

    def test_builtin_not_overridden(self):
        # EOT is built-in; a correction restating it must not be "added".
        fb.record_feedback({"vote": "down", "route": "data", "question": "q",
                            "correction": "EOT means Extension of Time"})
        assert fw._learn_jargon(fb.load_feedback()) == 0


class TestGoldenSet:
    def test_build_splits_good_and_review(self):
        fb.record_feedback({"vote": "up", "route": "data", "question": "good q"})
        fb.record_feedback({"vote": "down", "route": "document", "question": "bad q", "correction": "x"})
        res = gs.build_golden_set()
        assert res == {"total": 2, "good": 1, "needs_review": 1}
        rows = gs.load_golden_set()
        assert any(r.get("label") == "good" for r in rows)
        assert any(r.get("label") == "needs_review" for r in rows)


class TestSalientTerms:
    def test_drops_stopwords_and_short(self):
        terms = fw._salient_terms("how many steel fixers on Block A")
        assert "steel" in terms and "fixers" in terms
        assert "how" not in terms and "on" not in terms
