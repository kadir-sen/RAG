"""Tests for src.user_store — auth, CRUD, per-user usage, quota enforcement."""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.user_store import UserQuotaExceededError, UserStore


@pytest.fixture()
def store(tmp_path: Path) -> UserStore:
    return UserStore(db_path=tmp_path / "users.db")


def test_create_and_get_user(store: UserStore):
    record = store.create_user(
        "alice",
        "secret-pw",
        display_name="Alice",
        token_limit=5000,
        features={"correspondence": True},
    )
    assert record["username"] == "alice"
    assert record["display_name"] == "Alice"
    assert record["token_limit"] == 5000
    assert record["features"] == {"correspondence": True}
    assert record["is_active"] is True

    fetched = store.get_user("alice")
    assert fetched is not None
    assert fetched["features"] == {"correspondence": True}


def test_duplicate_user_rejected(store: UserStore):
    store.create_user("bob", "pw")
    with pytest.raises(ValueError):
        store.create_user("bob", "pw2")


def test_verify_password(store: UserStore):
    store.create_user("carol", "topsecret")
    assert store.verify_password("carol", "topsecret") is not None
    assert store.verify_password("carol", "wrong") is None
    assert store.verify_password("nobody", "topsecret") is None


def test_inactive_user_cannot_authenticate(store: UserStore):
    store.create_user("dave", "pw")
    store.update_user("dave", is_active=False)
    assert store.verify_password("dave", "pw") is None


def test_update_user_fields(store: UserStore):
    store.create_user("eve", "pw", token_limit=1000)
    updated = store.update_user(
        "eve",
        token_limit=2000,
        features={"correspondence": True, "provider_compare": False},
        display_name="Eve Q",
    )
    assert updated is not None
    assert updated["token_limit"] == 2000
    assert updated["features"]["correspondence"] is True
    assert updated["display_name"] == "Eve Q"


def test_increment_usage_and_quota(store: UserStore):
    store.create_user("frank", "pw", token_limit=100)
    store.increment_usage("frank", prompt_tokens=30, completion_tokens=20)
    snap = store.get_usage("frank")
    assert snap["used_tokens"] == 50
    assert snap["token_limit"] == 100
    assert snap["percent_remaining"] == 50.0

    # Still under limit — enforce_quota must not raise.
    store.enforce_quota("frank")

    store.increment_usage("frank", prompt_tokens=60, completion_tokens=0)
    with pytest.raises(UserQuotaExceededError):
        store.enforce_quota("frank")


def test_reset_usage(store: UserStore):
    store.create_user("grace", "pw", token_limit=500)
    store.increment_usage("grace", 100, 100)
    assert store.get_usage("grace")["used_tokens"] == 200
    snap = store.reset_usage("grace")
    assert snap["used_tokens"] == 0
    assert snap["total_calls"] == 0


def test_delete_user_soft(store: UserStore):
    store.create_user("heidi", "pw")
    assert store.delete_user("heidi", soft=True) is True
    record = store.get_user("heidi")
    assert record is not None
    assert record["is_active"] is False
    # Soft-deleted users cannot authenticate.
    assert store.verify_password("heidi", "pw") is None


def test_list_users(store: UserStore):
    store.create_user("a", "pw")
    store.create_user("b", "pw", role="admin")
    names = {u["username"] for u in store.list_users()}
    assert names == {"a", "b"}
