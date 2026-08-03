from types import SimpleNamespace

import pytest

from src import llm_client


def _offline(monkeypatch):
    monkeypatch.setattr(llm_client, "_current_model_policy", lambda: "demo-gemini-3.6-v1")
    monkeypatch.setattr(llm_client, "_GENAI_AVAILABLE", True)
    monkeypatch.setattr(llm_client, "_cache_get", lambda _key: None)
    monkeypatch.setattr(llm_client, "_cache_set", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(llm_client, "enforce_budget", lambda: None)
    monkeypatch.setattr(llm_client, "_enforce_user_quota", lambda: None)
    monkeypatch.setattr(llm_client, "record_usage", lambda *_args: None)
    monkeypatch.setattr(llm_client, "_record_run_usage", lambda *_args: None)


def test_demo_forces_gemini_36_and_minimal_for_lite_tasks(monkeypatch):
    _offline(monkeypatch)
    native = {}

    def fake_native(**kwargs):
        native.update(kwargs)
        return "ok", 100, 10, 5, 2, SimpleNamespace()

    attributed = {}
    monkeypatch.setattr(llm_client, "_gemini_generate_native", fake_native)
    monkeypatch.setattr(
        llm_client, "_attribute_to_current_user",
        lambda *args, **kwargs: attributed.update(kwargs),
    )
    response = llm_client.generate_text(
        "classify", provider="openai", model="gpt-5.6-sol",
        task_type="classification",
    )
    assert response.text == "ok"
    assert response.usage.provider == "gemini"
    assert response.usage.model == "gemini-3.6-flash"
    assert native["thinking_level"] == "minimal"
    assert attributed["model"] == "gemini-3.6-flash"
    assert attributed["reasoning_tokens"] == 5


def test_demo_structured_reports_use_gemini(monkeypatch):
    monkeypatch.setattr(llm_client, "_current_model_policy", lambda: "demo-gemini-3.6-v1")
    captured = {}

    def fake_generate(prompt, **kwargs):
        captured.update(kwargs)
        return llm_client.LLMResponse(
            text='{"answer":"yes"}',
            usage=llm_client.LLMUsage(model="gemini-3.6-flash", provider="gemini"),
        )

    monkeypatch.setattr(llm_client, "generate_text", fake_generate)
    result = llm_client.generate_response_json(
        "prompt", system="system",
        schema={"type": "object", "properties": {"answer": {"type": "string"}}},
        schema_name="answer",
    )
    assert result.raw == {"answer": "yes"}
    assert captured["provider"] == "gemini"
    assert captured["model"] == "gemini-3.6-flash"
    assert captured["thinking_level"] == "medium"


def test_unknown_model_price_fails_closed():
    with pytest.raises(ValueError, match="No pricing configured"):
        llm_client.estimate_cost_nanos("unknown-model", 1, 1)
