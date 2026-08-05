import sys

from scripts import configure_demo_account
from src.user_store import UserStore


def _run(monkeypatch, store, *, key_loader=lambda _ref: "valid-key-value"):
    monkeypatch.setattr(configure_demo_account, "UserStore", lambda: store)
    monkeypatch.setattr(
        configure_demo_account, "get_google_api_key_for_ref", key_loader,
    )
    monkeypatch.setenv("DEMO_TEST_PASSWORD", "demo2026")
    monkeypatch.setattr(sys, "argv", [
        "configure_demo_account.py",
        "--username", "demo",
        "--key-ref", "demo",
        "--credits", "5000",
        "--storage-limit-bytes", "30000000000",
        "--password-env", "DEMO_TEST_PASSWORD",
    ])
    return configure_demo_account.main()


def test_missing_demo_account_is_created_idempotently(monkeypatch, tmp_path):
    store = UserStore(tmp_path / "users.db")

    assert _run(monkeypatch, store) == 0
    user = store.get_user("demo")
    summary = store.billing.summary("demo")
    assert user["role"] == "user"
    assert user["is_active"] is True
    assert store.verify_password("demo", "demo2026") is not None
    assert summary["plan_type"] == "demo"
    assert summary["credits_total"] == 5000
    assert summary["markup_percent"] == 0
    assert summary["storage_limit_bytes"] == 30_000_000_000
    assert store.billing.get_account("demo")["provider_key_ref"] == "demo"

    charged = store.billing.record_charge(
        username="demo", provider="gemini", model="gemini-3.6-flash",
        prompt_tokens=100, completion_tokens=10, reasoning_tokens=5,
        provider_cost_nanos=1_000_000_000, idempotency_key="demo-cost-1",
    )
    assert charged["credits_used"] == 100
    assert charged["credits_remaining"] == 4900
    assert charged["credit_percent_remaining"] == 98

    assert _run(monkeypatch, store) == 0
    repeated = store.billing.summary("demo")
    assert repeated["credits_total"] == 5000
    assert repeated["credits_remaining"] == 4900


def test_invalid_key_does_not_create_partial_account(monkeypatch, tmp_path):
    store = UserStore(tmp_path / "users.db")

    def reject_key(_ref):
        raise RuntimeError("provider_key_secret_invalid")

    assert _run(monkeypatch, store, key_loader=reject_key) == 2
    assert store.get_user("demo") is None
