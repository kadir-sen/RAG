"""Lightweight fastembed (ONNX) embedding for low-RAM servers.

Runs BAAI/bge-base-en-v1.5 via fastembed/onnxruntime instead of torch +
sentence-transformers, cutting resident memory by ~0.5-1 GB (fits a 2 GB box)
and shrinking the Docker image (no torch). It is wire-compatible with vectors
created by the sentence-transformers bge-base path BECAUSE it applies the SAME
bge query instruction on queries and embeds documents plain — empirically the
same top-k results and near-identical cosine scores.

Used when EMBEDDING_PROVIDER=fastembed.
"""
from __future__ import annotations

from typing import Any, List

from llama_index.core.embeddings import BaseEmbedding
from pydantic import PrivateAttr

# bge-en-v1.5 recommends this instruction on the QUERY side only; documents are
# embedded plain. Must match what the corpus was ingested with.
BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class FastEmbedEmbedding(BaseEmbedding):
    """LlamaIndex embedding backed by fastembed (ONNX). No torch."""

    _model: Any = PrivateAttr()
    _query_instruction: str = PrivateAttr()

    def __init__(self, model_name: str = "BAAI/bge-base-en-v1.5",
                 query_instruction: str = BGE_QUERY_INSTRUCTION, **kwargs: Any) -> None:
        super().__init__(model_name=model_name, **kwargs)
        from fastembed import TextEmbedding
        self._model = TextEmbedding(model_name=model_name)
        self._query_instruction = query_instruction

    def _embed_one(self, text: str) -> List[float]:
        return list(self._model.embed([text]))[0].tolist()

    # documents — plain
    def _get_text_embedding(self, text: str) -> List[float]:
        return self._embed_one(text)

    def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        return [e.tolist() for e in self._model.embed(list(texts))]

    # queries — with the bge instruction so they match the doc vector space
    def _get_query_embedding(self, query: str) -> List[float]:
        return self._embed_one(self._query_instruction + query)

    # async variants just delegate to sync (onnxruntime is sync)
    async def _aget_text_embedding(self, text: str) -> List[float]:
        return self._get_text_embedding(text)

    async def _aget_query_embedding(self, query: str) -> List[float]:
        return self._get_query_embedding(query)
