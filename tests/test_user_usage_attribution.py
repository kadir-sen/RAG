"""Regression: per-user token usage must be recorded so the quota bar isn't
stuck at 100%. The bug was that the auth dependency sets current_user_var in a
FastAPI threadpool context that never reaches the query worker thread, so
llm_client._attribute_to_current_user saw no user and never incremented usage.
The orchestrator now re-stamps current_user_var; these tests lock the contract
that attribution works when the contextvar is set (and is a no-op when it isn't)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-please-replace-in-prod")


@pytest.fixture()
def store(tmp_path, monkeypatch):
    from src import user_store as user_store_module
    instance = user_store_module.UserStore(db_path=tmp_path / "users.db")
    monkeypatch.setattr(user_store_module.UserStore, "_instance", instance)
    return instance


def test_get_usage_starts_full_then_drops(store):
    store.create_user("alice", "secret", token_limit=1000)
    snap = store.get_usage("alice")
    assert snap["used_tokens"] == 0 and snap["percent_remaining"] == 100.0
    store.increment_usage("alice", prompt_tokens=200, completion_tokens=100)
    snap = store.get_usage("alice")
    assert snap["used_tokens"] == 300
    assert snap["token_limit"] == 1000
    assert snap["percent_remaining"] == 70.0  # (1 - 300/1000)*100


def test_attribution_records_when_user_in_context(store, monkeypatch):
    """With current_user_var set (as the orchestrator now does), an LLM call is
    mirrored to the user's counter — this is the fix for the always-100% bug."""
    from backend.core.security import current_user_var, UserContext
    from src import llm_client

    store.create_user("bob", "secret", token_limit=10_000)
    token = current_user_var.set(UserContext(
        username="bob", role="user", display_name="Bob", features={}, token_limit=10_000))
    try:
        llm_client._attribute_to_current_user(prompt_tok=120, comp_tok=80)
    finally:
        current_user_var.reset(token)

    snap = store.get_usage("bob")
    assert snap["used_tokens"] == 200
    assert snap["percent_remaining"] == 98.0  # (1 - 200/10000)*100


def test_attribution_noop_without_user(store):
    """No user in context (background/CLI) → no per-user write, no crash."""
    from backend.core.security import current_user_var
    from src import llm_client

    store.create_user("carol", "secret", token_limit=10_000)
    current_user_var.set(None)
    llm_client._attribute_to_current_user(prompt_tok=500, comp_tok=500)
    assert store.get_usage("carol")["used_tokens"] == 0
