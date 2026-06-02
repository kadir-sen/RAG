"""Tests for the JWT auth flow: token issuance, decode, FastAPI deps."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

# A stable secret for the test process. Must be set before importing security.
os.environ.setdefault("JWT_SECRET", "test-secret-please-replace-in-prod")


@pytest.fixture()
def store(tmp_path, monkeypatch):
    from src import user_store as user_store_module

    db = tmp_path / "users.db"
    instance = user_store_module.UserStore(db_path=db)
    # Swap the module-level singleton so security.get_current_user resolves to
    # this test instance.
    monkeypatch.setattr(user_store_module.UserStore, "_instance", instance)
    return instance


@pytest.fixture()
def app(store):
    from backend.api import auth as auth_router
    from backend.core.security import (
        UserContext,
        get_current_user,
        require_admin,
    )

    fastapi_app = FastAPI()
    fastapi_app.include_router(auth_router.router, prefix="/api")

    @fastapi_app.get("/api/whoami")
    def whoami(user: UserContext = next(iter([])) if False else None):
        # Fallback signature without Depends to make pytest happy at import time.
        raise HTTPException(500, "unused")

    from fastapi import Depends

    @fastapi_app.get("/api/me-test")
    def me_test(user: UserContext = Depends(get_current_user)):
        return {"username": user.username, "role": user.role}

    @fastapi_app.get("/api/admin-test")
    def admin_test(user: UserContext = Depends(require_admin)):
        return {"username": user.username}

    return fastapi_app


def test_login_returns_token(app, store):
    store.create_user("alice", "secret", token_limit=1000)
    client = TestClient(app)
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "secret"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["username"] == "alice"
    assert body["user"]["percent_remaining"] == 100.0


def test_login_wrong_password(app, store):
    store.create_user("bob", "pw")
    client = TestClient(app)
    resp = client.post("/api/auth/login", json={"username": "bob", "password": "wrong"})
    assert resp.status_code == 401


def test_me_requires_token(app, store):
    store.create_user("carol", "pw")
    client = TestClient(app)
    assert client.get("/api/me-test").status_code == 401

    token = client.post(
        "/api/auth/login", json={"username": "carol", "password": "pw"}
    ).json()["access_token"]
    resp = client.get("/api/me-test", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "carol"


def test_admin_dependency(app, store):
    store.create_user("dave", "pw", role="user")
    store.create_user("evelyn", "pw", role="admin")
    client = TestClient(app)
    dave_token = client.post(
        "/api/auth/login", json={"username": "dave", "password": "pw"}
    ).json()["access_token"]
    evelyn_token = client.post(
        "/api/auth/login", json={"username": "evelyn", "password": "pw"}
    ).json()["access_token"]

    r1 = client.get("/api/admin-test", headers={"Authorization": f"Bearer {dave_token}"})
    assert r1.status_code == 403
    r2 = client.get(
        "/api/admin-test", headers={"Authorization": f"Bearer {evelyn_token}"}
    )
    assert r2.status_code == 200


def test_invalid_token(app, store):
    client = TestClient(app)
    resp = client.get("/api/me-test", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401
