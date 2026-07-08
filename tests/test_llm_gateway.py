"""LLM gateway: selection, fallback chain, error sanitization, usage logging."""

import re
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.llm import gateway, errors, policy
from src.llm.errors import LLMErrorType, classify_error, sanitize
from src.llm.policy import TASK_POLICY, select
from src.llm.registry import MODEL_GROUPS, resolve_group

FORBIDDEN_TOKENS = ["429", "googleapis", "quota", "billing", "resource_exhausted",
                    "permission_denied", "traceback", "http", "api key"]


def _usage(pt=10, ct=5, cost=0.001):
    return SimpleNamespace(prompt_tokens=pt, completion_tokens=ct,
                           total_tokens=pt + ct, cost_estimate=cost,
                           model="gemini-2.5-flash", latency_ms=100.0,
                           cache_hit=False, provider="gemini")


def _resp(text="ok", raw=None):
    return SimpleNamespace(text=text, raw=raw, usage=_usage())


@pytest.fixture(autouse=True)
def no_usage_writes(monkeypatch):
    # keep tests DB-free
    monkeypatch.setattr("src.llm.usage.log_usage_event", lambda **k: None)
    monkeypatch.setattr(gateway, "_record_trace", lambda u: None)
    yield


class TestSelection:
    def test_all_tasks_resolve(self):
        for t in TASK_POLICY:
            chain = select(t)
            assert chain.policy.task_type == t
            # every task has at least one enabled model
            assert chain.models, t

    def test_standard_synthesis_chain_order(self):
        m = [s.model_id for s in select("rag_answer_synthesis").models]
        assert m[0] == "gemini_flash" and "gemini_flash_lite" in m

    def test_disabled_models_filtered(self):
        # deepseek/claude are enabled=False → never appear
        for t in TASK_POLICY:
            ids = [s.model_id for s in select(t).models]
            assert "deepseek_chat" not in ids and "claude_sonnet" not in ids

    def test_no_hardcoded_model_strings_outside_registry(self):
        import pathlib
        root = pathlib.Path("src/llm")
        pat = re.compile(r"gemini-2\.5|gemini-1\.5|gpt-4|claude-sonnet")
        for f in root.glob("*.py"):
            if f.name == "registry.py":
                continue
            assert not pat.search(f.read_text()), f"model literal in {f.name}"


class TestErrorClassification:
    @pytest.mark.parametrize("text,expected", [
        ("LLM call failed (gemini): 429 You exceeded your current quota", LLMErrorType.RATE_LIMIT),
        ("LLM call failed (gemini): 403 PERMISSION_DENIED generativelanguage.googleapis.com", LLMErrorType.BILLING_QUOTA),
        ("LLM call timeout after 30s", LLMErrorType.TIMEOUT),
        ("LLM call failed (gemini): 503 UNAVAILABLE overloaded", LLMErrorType.PROVIDER_DOWN),
        ("context length exceeded maximum context", LLMErrorType.CONTEXT_WINDOW),
        ("blocked by safety content policy", LLMErrorType.CONTENT_POLICY),
        ("LLM did not return valid JSON", LLMErrorType.MALFORMED_JSON),
        ("something totally weird", LLMErrorType.UNKNOWN),
    ])
    def test_regex_classification(self, text, expected):
        assert classify_error(RuntimeError(text)) == expected

    def test_budget_reraised(self):
        from src.usage_tracker import BudgetExceededError
        with pytest.raises(BudgetExceededError):
            classify_error(BudgetExceededError("limit reached"))

    def test_quota_reraised(self):
        from src.user_store import UserQuotaExceededError
        with pytest.raises(UserQuotaExceededError):
            classify_error(UserQuotaExceededError("user", 100, 50))


class TestSanitizeGuard:
    def test_no_task_leaks_forbidden_tokens(self):
        for t, pol in TASK_POLICY.items():
            for et in LLMErrorType:
                msg = sanitize(pol, et).lower()
                for tok in FORBIDDEN_TOKENS:
                    assert tok not in msg, f"{t}/{et} leaked '{tok}': {msg}"


class TestGatewayFallback:
    def test_success_primary(self):
        with patch.object(gateway, "_invoke", return_value=_resp("hi")):
            r = gateway.complete("rag_answer_synthesis", "q")
        assert r.status == "success" and r.fallback_level == 0
        assert r.text == "hi" and r.model_used == "gemini_flash"

    def test_fallback_to_second_model(self):
        calls = []
        def fake(spec, *a, **k):
            calls.append(spec.model_id)
            if spec.model_id == "gemini_flash":
                raise RuntimeError("LLM call failed (gemini): 429 quota")
            return _resp("recovered")
        with patch.object(gateway, "_invoke", side_effect=fake):
            r = gateway.complete("rag_answer_synthesis", "q")
        assert r.status == "fallback" and r.fallback_level == 1
        assert r.text == "recovered"
        # rate-limit → no same-model retry: flash tried exactly once
        assert calls.count("gemini_flash") == 1

    def test_billing_no_same_model_retry(self):
        calls = []
        def fake(spec, *a, **k):
            calls.append(spec.model_id)
            raise RuntimeError("LLM call failed (gemini): 403 billing generativelanguage.googleapis.com")
        with patch.object(gateway, "_invoke", side_effect=fake):
            r = gateway.complete("rag_answer_synthesis", "q")
        # each model tried exactly once, no repeats
        assert len(calls) == len(set(calls))
        assert r.status == "degraded"

    def test_timeout_one_retry_then_advance(self):
        calls = []
        def fake(spec, *a, **k):
            calls.append(spec.model_id)
            if spec.model_id == "gemini_flash":
                raise RuntimeError("LLM call timeout after 30s")
            return _resp("ok")
        with patch.object(gateway, "_invoke", side_effect=fake):
            r = gateway.complete("rag_answer_synthesis", "q")
        # timeout allows one same-model retry (policy retries=1) then advances
        assert calls.count("gemini_flash") == 2
        assert r.status == "fallback"

    def test_fail_open_returns_degraded_empty_text(self):
        with patch.object(gateway, "_invoke",
                          side_effect=RuntimeError("LLM call failed (gemini): 429 quota")):
            r = gateway.complete("trust_guard_verification", "q")  # fail_open=True
        assert r.status == "degraded"
        assert r.text == ""  # fail-open → empty, caller keeps its data
        assert "unverified" in r.degraded_message.lower()

    def test_fail_closed_returns_sanitized_text(self):
        with patch.object(gateway, "_invoke",
                          side_effect=RuntimeError("LLM call failed (gemini): 429 quota")):
            r = gateway.complete("sql_generation", "q")  # fail_open=False
        assert r.status == "degraded"
        assert "temporarily unavailable" in r.text.lower()
        for tok in FORBIDDEN_TOKENS:
            assert tok not in r.text.lower()

    def test_deterministic_fallback_used(self):
        det = gateway.GatewayResult(text="deterministic answer", status="success")
        with patch.object(gateway, "_invoke",
                          side_effect=RuntimeError("LLM call failed (gemini): 429 quota")):
            r = gateway.complete("sql_generation", "q",
                                 deterministic_fn=lambda: det)
        assert r.fallback_level == -1 and r.text == "deterministic answer"

    def test_budget_propagates_not_sanitized(self):
        from src.usage_tracker import BudgetExceededError
        with patch.object(gateway, "_invoke",
                          side_effect=BudgetExceededError("limit")):
            with pytest.raises(BudgetExceededError):
                gateway.complete("rag_answer_synthesis", "q")


class TestUsageLogging:
    def test_logs_success_fallback_error(self, monkeypatch):
        rows = []
        monkeypatch.setattr("src.llm.usage.log_usage_event",
                            lambda **k: rows.append(k))
        def fake(spec, *a, **k):
            if spec.model_id == "gemini_flash":
                raise RuntimeError("LLM call failed (gemini): 429 quota")
            return _resp("ok")
        with patch.object(gateway, "_invoke", side_effect=fake):
            gateway.complete("rag_answer_synthesis", "q")
        statuses = [r["status"] for r in rows]
        assert "error" in statuses and "fallback" in statuses
