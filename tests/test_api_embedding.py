"""ApiEmbedding: remote bge must mirror fastembed's wire behavior exactly —
documents plain, queries with the bge instruction, OpenAI-compatible payload."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.api_embedding import ApiEmbedding, _BATCH_SIZE  # noqa: E402
from src.fastembed_embedding import BGE_QUERY_INSTRUCTION  # noqa: E402


class _FakeResponse:
    def __init__(self, n_embeddings: int):
        self._n = n_embeddings

    def raise_for_status(self):
        pass

    def json(self):
        return {"data": [
            {"index": i, "embedding": [float(i)] * 768} for i in range(self._n)
        ]}


@pytest.fixture
def captured(monkeypatch):
    calls: list[dict] = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers})
        return _FakeResponse(len(json["input"]))

    monkeypatch.setattr("src.api_embedding.requests.post", fake_post)
    return calls


def _model() -> ApiEmbedding:
    return ApiEmbedding(url="https://api.example.com/v1/embeddings",
                        api_key="k", model_name="BAAI/bge-base-en-v1.5")


def test_query_gets_bge_instruction(captured):
    _model().get_query_embedding("fasta related documents")
    assert captured[0]["json"]["input"] == [
        BGE_QUERY_INSTRUCTION + "fasta related documents"
    ]


def test_document_embedded_plain(captured):
    _model().get_text_embedding("chunk text")
    assert captured[0]["json"]["input"] == ["chunk text"]
    assert captured[0]["json"]["model"] == "BAAI/bge-base-en-v1.5"
    assert captured[0]["headers"]["Authorization"] == "Bearer k"


def test_batching_splits_large_ingest(captured):
    texts = [f"t{i}" for i in range(_BATCH_SIZE + 5)]
    vecs = _model().get_text_embedding_batch(texts)
    assert len(vecs) == len(texts)
    # LlamaIndex sub-batches via embed_batch_size before our _BATCH_SIZE cap;
    # the invariants that matter: every request stays within the provider cap
    # and no text is lost across batches.
    assert all(len(c["json"]["input"]) <= _BATCH_SIZE for c in captured)
    assert sum(len(c["json"]["input"]) for c in captured) == len(texts)


def test_dimension_is_768(captured):
    vec = _model().get_text_embedding("dimension probe")
    assert len(vec) == 768


def test_missing_config_raises():
    with pytest.raises(RuntimeError, match="EMBEDDING_API_URL"):
        ApiEmbedding(url="", api_key="")
