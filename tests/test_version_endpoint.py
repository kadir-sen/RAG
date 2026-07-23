"""GET /api/version — "which build is live?" answerable with one request.

The deploy previously could only be verified by SSH-ing to the box and reading
`docker ps`. These tests pin the contract the deploy log and any operator relies
on: the running commit, the build stamp, and the feature flags that actually
change behaviour.
"""

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from backend.main import create_app
    return TestClient(create_app())


def test_health_still_minimal(client):
    """The deploy gate + docker healthcheck poll this; keep it cheap."""
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_version_reports_commit_and_build_time(client, monkeypatch):
    monkeypatch.setenv("GIT_SHA", "abc123def456")
    monkeypatch.setenv("BUILD_TIME", "2026-07-19T10:00:00Z")
    r = client.get("/api/version")
    assert r.status_code == 200
    body = r.json()
    assert body["commit"] == "abc123def456"
    assert body["built_at"] == "2026-07-19T10:00:00Z"


def test_version_degrades_when_not_baked(client, monkeypatch):
    """A locally-run (non-image) build must still answer, not 500."""
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.delenv("BUILD_TIME", raising=False)
    r = client.get("/api/version")
    assert r.status_code == 200
    assert r.json()["commit"] == "unknown"


def test_version_exposes_feature_flags(client):
    r = client.get("/api/version")
    feats = r.json()["features"]
    # the flags that change routing/retrieval behaviour must be visible
    for key in ("compound_planner", "llm_decomposer", "deterministic_rerank",
                "cross_encoder", "hybrid_retrieval"):
        assert key in feats
        assert isinstance(feats[key], bool)


def test_version_leaks_no_secrets(client):
    """Only booleans + build stamp — never keys, hosts, or config values."""
    body = client.get("/api/version").json()
    assert set(body.keys()) == {"commit", "built_at", "features"}
    blob = str(body).lower()
    for forbidden in ("key", "token", "password", "secret", "api_key"):
        assert forbidden not in blob
