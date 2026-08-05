from src import router
from src.model_profiles import MODEL_CAPABILITIES


class _LocalEmbedding:
    def __init__(self):
        self.batches = []

    def get_text_embedding_batch(self, texts):
        self.batches.append(list(texts))
        return [[float(index + 1), 1.0] for index, _ in enumerate(texts)]


def test_router_anchor_embeddings_reuse_configured_local_model(monkeypatch):
    local = _LocalEmbedding()
    monkeypatch.setattr(router, "_routing_embed_model", lambda: local)
    monkeypatch.setattr(router, "_anchor_embeddings", None)
    value = router._get_anchor_embeddings()
    assert set(value) == {"data", "document", "hybrid"}
    assert sum(len(batch) for batch in local.batches) > 0


def test_ingestion_models_have_provider_hard_limits():
    for model in ("gemini-2.5-flash", "gemini-2.5-flash-lite"):
        assert MODEL_CAPABILITIES[model].input_tokens == 1_048_576
        assert MODEL_CAPABILITIES[model].output_tokens == 65_536
