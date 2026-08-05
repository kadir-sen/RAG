from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from src.billing_store import (
    BillingStore, CreditBalanceExceededError, StorageQuotaExceededError,
)


@pytest.fixture
def billing(tmp_path):
    path = tmp_path / "users.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE users(username TEXT PRIMARY KEY)")
    conn.executemany("INSERT INTO users VALUES (?)", [("demo",), ("legacy",)])
    conn.commit(); conn.close()
    store = BillingStore(path)
    store.provision_account(
        "demo", plan_type="demo", initial_credits=1000,
        markup_bps=3000, storage_limit_bytes=100,
        model_policy="demo-gemini-3.6-v1",
    )
    store.provision_account("legacy", plan_type="legacy")
    return store


def test_markup_and_project_ledger(billing):
    summary = billing.record_charge(
        username="demo", project_id="p1", provider="gemini",
        model="gemini-3.6-flash", prompt_tokens=100, completion_tokens=50,
        provider_cost_nanos=1_000_000_000, idempotency_key="call-1",
    )
    assert summary["credits_remaining"] == 870.0
    assert summary["credits_used"] == 130.0
    group = billing.usage(username="demo", project_id="p1")["groups"][0]
    assert group["estimated_provider_cost_usd"] == 1.0
    assert group["retail_credit"] == 130.0
    assert group["debited_credit"] == 130.0
    assert group["markup_percent"] == 30.0
    assert group["model"] == "gemini-3.6-flash"


def test_idempotency_and_cache_are_free(billing):
    kwargs = dict(
        username="demo", provider="gemini", model="gemini-3.6-flash",
        prompt_tokens=100, completion_tokens=10, provider_cost_nanos=10_000_000,
        idempotency_key="same",
    )
    billing.record_charge(**kwargs)
    once = billing.summary("demo")["credits_remaining"]
    billing.record_charge(**kwargs)
    assert billing.summary("demo")["credits_remaining"] == once
    billing.record_charge(
        username="demo", provider="gemini", model="gemini-3.6-flash",
        prompt_tokens=100, completion_tokens=10, cached_tokens=100,
        provider_cost_nanos=0, usage_source="cache", idempotency_key="cache",
    )
    assert billing.summary("demo")["credits_remaining"] == once


def test_ledger_rejects_update_and_delete(billing):
    billing.record_charge(
        username="demo", provider="gemini", model="gemini-3.6-flash",
        prompt_tokens=1, completion_tokens=1, provider_cost_nanos=1,
        idempotency_key="immutable",
    )
    with billing._connect() as conn:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "UPDATE billing_ledger SET note='changed' WHERE idempotency_key='immutable'"
            )
    with billing._connect() as conn:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM billing_ledger WHERE idempotency_key='immutable'")
def test_last_call_completes_then_future_calls_are_blocked(billing):
    summary = billing.record_charge(
        username="demo", provider="gemini", model="gemini-3.6-flash",
        prompt_tokens=1, completion_tokens=1,
        provider_cost_nanos=10_000_000_000, idempotency_key="overshoot",
    )
    assert summary["credits_remaining"] == 0
    group = billing.usage(username="demo")["groups"][0]
    assert group["uncovered_credit"] == 300.0
    assert group["uncovered_provider_cost_usd"] == pytest.approx(2.307692308)
    with pytest.raises(CreditBalanceExceededError):
        billing.enforce_credits("demo")


def test_adjustment_requires_reason_and_restores_balance(billing):
    with pytest.raises(ValueError):
        billing.adjust_credits("demo", 10, "")
    value = billing.adjust_credits("demo", 25, "Approved top-up")
    assert value["credits_total"] == 1025
    assert value["credits_remaining"] == 1025


def test_storage_is_user_wide_duplicate_safe_and_releasable(billing):
    billing.register_storage(
        username="demo", project_id="p1", file_id="a", file_path="/a", size_bytes=60,
    )
    billing.register_storage(
        username="demo", project_id="p1", file_id="a", file_path="/a", size_bytes=60,
    )
    assert billing.summary("demo")["storage_used_bytes"] == 60
    with pytest.raises(StorageQuotaExceededError):
        billing.register_storage(
            username="demo", project_id="p2", file_id="b", file_path="/b", size_bytes=50,
        )
    billing.release_storage(project_id="p1", file_id="a")
    assert billing.summary("demo")["storage_used_bytes"] == 0


def test_concurrent_storage_checks_cannot_oversubscribe(billing):
    def add(project):
        try:
            billing.register_storage(
                username="demo", project_id=project, file_id=project,
                file_path=f"/{project}", size_bytes=60,
            )
            return True
        except StorageQuotaExceededError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(add, ["p1", "p2"]))
    assert sorted(results) == [False, True]
    assert billing.summary("demo")["storage_used_bytes"] == 60


def test_dedicated_provider_key_binding_stores_only_alias(billing):
    value = billing.update_account("demo", plan_type="demo", provider_key_ref="demo")
    assert value["plan_type"] == "demo"
    assert value["dedicated_provider_key"] is True
    assert billing.get_account("demo")["provider_key_ref"] == "demo"
    assert "AQ." not in repr(billing.get_account("demo"))

    value = billing.update_account("demo", provider_key_ref="")
    assert value["dedicated_provider_key"] is False


@pytest.mark.parametrize("bad_ref", ["../demo", "/demo", "demo/key", "two words"])
def test_provider_key_binding_rejects_unsafe_aliases(billing, bad_ref):
    with pytest.raises(ValueError, match="provider_key_ref"):
        billing.update_account("demo", provider_key_ref=bad_ref)


def test_provider_key_column_is_added_without_rewriting_existing_account(tmp_path):
    path = tmp_path / "legacy-users.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE users(username TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO users VALUES ('demo')")
    conn.execute(
        """CREATE TABLE billing_accounts (
        username TEXT PRIMARY KEY, plan_type TEXT NOT NULL,
        credits_granted_micro INTEGER NOT NULL, credits_balance_micro INTEGER NOT NULL,
        markup_bps INTEGER NOT NULL, storage_limit_bytes INTEGER NOT NULL,
        storage_used_bytes INTEGER NOT NULL, model_policy TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"""
    )
    conn.execute(
        "INSERT INTO billing_accounts VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("demo", "demo", 7, 6, 3000, 30_000_000_000, 123,
         "old-policy", "before", "before"),
    )
    conn.commit(); conn.close()

    migrated = BillingStore(path)
    row = migrated.get_account("demo")
    assert row["credits_balance_micro"] == 6
    assert row["storage_used_bytes"] == 123
    assert row["provider_key_ref"] == ""
