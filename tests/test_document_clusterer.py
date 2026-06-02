"""Tests for src/document_clusterer.py — clustering math + assignment.

These tests exercise the pure-math pieces (_l2_normalize, _cosine, _run_clustering)
and the online assignment / persistence path with mocked centroids. Pinecone
and LLM calls are stubbed so the suite stays hermetic.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from src import document_clusterer as dc


# ── Math helpers ────────────────────────────────────────────────────


def test_l2_normalize_unit_vector():
    v = np.array([3.0, 4.0, 0.0])
    out = dc._l2_normalize(v)
    assert pytest.approx(np.linalg.norm(out), abs=1e-6) == 1.0


def test_l2_normalize_zero_vector_safe():
    v = np.zeros(8)
    out = dc._l2_normalize(v)
    assert np.array_equal(out, v)


def test_cosine_identical_vectors():
    a = dc._l2_normalize(np.array([1.0, 2.0, 3.0]))
    assert pytest.approx(dc._cosine(a, a), abs=1e-6) == 1.0


def test_cosine_orthogonal_vectors():
    a = dc._l2_normalize(np.array([1.0, 0.0]))
    b = dc._l2_normalize(np.array([0.0, 1.0]))
    assert pytest.approx(dc._cosine(a, b), abs=1e-6) == 0.0


# ── Clustering algorithm ────────────────────────────────────────────


def _synthetic_centroids(n_groups: int = 5, per_group: int = 4, dim: int = 16, seed: int = 7):
    """Build n_groups well-separated clusters of unit vectors."""
    rng = np.random.default_rng(seed)
    out = []
    for g in range(n_groups):
        # Distinct mean direction per group: one-hot-ish in different axes.
        base = np.zeros(dim)
        base[g % dim] = 5.0
        for _ in range(per_group):
            noise = rng.normal(0, 0.05, size=dim)
            v = base + noise
            out.append(dc._l2_normalize(v))
    return np.stack(out, axis=0)


def test_run_clustering_separates_synthetic_groups():
    """HDBSCAN (or fallback) should identify multiple clusters on clean data."""
    inst = dc.DocumentClusterer()
    X = _synthetic_centroids(n_groups=5, per_group=4)
    labels = inst._run_clustering(X)
    # Distinct non-noise labels found
    unique = set(int(l) for l in labels if l != -1)
    assert len(unique) >= 3, f"Expected at least 3 clusters, got labels={labels}"


# ── Online assignment ──────────────────────────────────────────────


@pytest.fixture
def isolated_clusterer(tmp_path, monkeypatch):
    """Provide a DocumentClusterer wired to a temp clusters.json and no
    Pinecone/registry dependency."""
    # Redirect CLUSTERS_FILE
    monkeypatch.setattr(dc, "CLUSTERS_FILE", tmp_path / "document_clusters.json")
    # Reset singleton so fresh state is loaded for this test
    dc.DocumentClusterer._instance = None
    inst = dc.DocumentClusterer()
    # Stub registry persistence mirror to a no-op
    monkeypatch.setattr(
        dc.DocumentClusterer,
        "_persist_locked",
        lambda self: None if False else dc.DocumentClusterer._persist_locked.__wrapped__(self) if hasattr(dc.DocumentClusterer._persist_locked, "__wrapped__") else None,
        raising=False,
    )
    # Use original persist but disable registry mirror by monkeypatching
    # document_registry import to fail gracefully.
    yield inst
    dc.DocumentClusterer._instance = None


def _seed_two_clusters(inst):
    """Inject two pre-existing clusters with known centroids."""
    c1 = dc._l2_normalize(np.array([1.0, 0.0, 0.0, 0.0]))
    c2 = dc._l2_normalize(np.array([0.0, 1.0, 0.0, 0.0]))
    inst._clusters = {
        "c_one": dc.ClusterEntry(cluster_id="c_one", label="One", centroid=c1.tolist(), doc_count=3),
        "c_two": dc.ClusterEntry(cluster_id="c_two", label="Two", centroid=c2.tolist(), doc_count=4),
    }
    inst._assignments = {}


def test_assign_new_doc_matches_close_centroid(isolated_clusterer, monkeypatch):
    inst = isolated_clusterer
    _seed_two_clusters(inst)

    near_c1 = dc._l2_normalize(np.array([0.95, 0.05, 0.0, 0.0]))

    # Stub centroid fetch + persistence side effects
    monkeypatch.setattr(inst, "fetch_doc_centroid", lambda doc_id, use_cache=False: near_c1)
    monkeypatch.setattr(inst, "_persist_locked", lambda: None)

    cid, label = inst.assign_new_doc("new-doc-1")
    assert cid == "c_one", f"Expected match to c_one, got {cid}"
    assert label == "One"


def test_assign_new_doc_falls_back_to_uncategorized(isolated_clusterer, monkeypatch):
    inst = isolated_clusterer
    _seed_two_clusters(inst)

    # Equidistant + cosine well below 0.55 threshold
    off_axis = dc._l2_normalize(np.array([0.0, 0.0, 1.0, 0.0]))

    monkeypatch.setattr(inst, "fetch_doc_centroid", lambda doc_id, use_cache=False: off_axis)
    monkeypatch.setattr(inst, "_persist_locked", lambda: None)

    cid, label = inst.assign_new_doc("low-sim-doc")
    assert cid == dc.UNCATEGORIZED_ID
    assert label == dc.UNCATEGORIZED_LABEL


def test_assign_new_doc_without_centroid_goes_uncategorized(isolated_clusterer, monkeypatch):
    inst = isolated_clusterer
    _seed_two_clusters(inst)

    monkeypatch.setattr(inst, "fetch_doc_centroid", lambda doc_id, use_cache=False: None)
    monkeypatch.setattr(inst, "_persist_locked", lambda: None)

    cid, _ = inst.assign_new_doc("no-vectors")
    assert cid == dc.UNCATEGORIZED_ID


# ── Forget / delete cleanup ────────────────────────────────────────


def test_forget_doc_decrements_cluster_and_removes_empty(isolated_clusterer, monkeypatch):
    inst = isolated_clusterer
    inst._clusters = {
        "c_alpha": dc.ClusterEntry(
            cluster_id="c_alpha", label="Alpha", centroid=[1.0, 0.0], doc_count=1,
        ),
    }
    inst._assignments = {"doc-a": "c_alpha"}
    monkeypatch.setattr(inst, "_persist_locked", lambda: None)

    inst.forget_doc("doc-a")
    assert "doc-a" not in inst._assignments
    assert "c_alpha" not in inst._clusters  # auto-removed when doc_count hits 0
