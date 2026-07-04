"""Remote bge embeddings over an OpenAI-compatible /embeddings endpoint.

Frees the ~600 MB the local fastembed/ONNX model costs on the 2 GB server by
embedding QUERIES via a hosted copy of the SAME model (BAAI/bge-base-en-v1.5,
768-dim). Wire-compatible with the existing Qdrant corpus for the same reason
fastembed is: documents are embedded plain, queries get the bge query
instruction — only the place the math runs changes.

Works with any OpenAI-compatible embeddings API that serves the model
(DeepInfra, Together, HuggingFace router, ...). Configure via:
    EMBEDDING_PROVIDER=api
    EMBEDDING_API_URL=https://api.deepinfra.com/v1/openai/embeddings
    EMBEDDING_API_KEY=<provider key>
    LOCAL_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5   (reused as the model name)
"""
from __future__ import annotations

from typing import Any, List

import requests
from llama_index.core.embeddings import BaseEmbedding
from pydantic import PrivateAttr

from .fastembed_embedding import BGE_QUERY_INSTRUCTION
from .logger import logger

_TIMEOUT_S = 30
_MAX_RETRIES = 2
_BATCH_SIZE = 64  # ingest batches; providers cap request sizes


class ApiEmbedding(BaseEmbedding):
    """LlamaIndex embedding backed by a remote OpenAI-compatible endpoint."""

    _url: str = PrivateAttr()
    _api_key: str = PrivateAttr()
    _query_instruction: str = PrivateAttr()

    def __init__(self, url: str, api_key: str,
                 model_name: str = "BAAI/bge-base-en-v1.5",
                 query_instruction: str = BGE_QUERY_INSTRUCTION,
                 **kwargs: Any) -> None:
        super().__init__(model_name=model_name, **kwargs)
        if not url or not api_key:
            raise RuntimeError(
                "EMBEDDING_PROVIDER=api requires EMBEDDING_API_URL and "
                "EMBEDDING_API_KEY to be set."
            )
        self._url = url
        self._api_key = api_key
        self._query_instruction = query_instruction

    def _post(self, texts: List[str]) -> List[List[float]]:
        payload = {"model": self.model_name, "input": texts, "encoding_format": "float"}
        headers = {"Authorization": f"Bearer {self._api_key}"}
        last_err: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = requests.post(self._url, json=payload, headers=headers,
                                     timeout=_TIMEOUT_S)
                resp.raise_for_status()
                data = resp.json()["data"]
                # OpenAI contract: order matches input, but sort by index anyway.
                data.sort(key=lambda d: d.get("index", 0))
                return [d["embedding"] for d in data]
            except Exception as e:  # noqa: BLE001 — retry any transport/HTTP error
                last_err = e
                if attempt < _MAX_RETRIES:
                    logger.warning(f"[ApiEmbedding] attempt {attempt + 1} failed: {e}")
        raise RuntimeError(f"Embedding API call failed after retries: {last_err}")

    # documents — plain (must match how the corpus was ingested)
    def _get_text_embedding(self, text: str) -> List[float]:
        return self._post([text])[0]

    def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        out: List[List[float]] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            out.extend(self._post(list(texts[i:i + _BATCH_SIZE])))
        return out

    # queries — with the bge instruction so they match the doc vector space
    def _get_query_embedding(self, query: str) -> List[float]:
        return self._post([self._query_instruction + query])[0]

    # async variants delegate to sync (requests is sync; call volume is tiny)
    async def _aget_text_embedding(self, text: str) -> List[float]:
        return self._get_text_embedding(text)

    async def _aget_query_embedding(self, query: str) -> List[float]:
        return self._get_query_embedding(query)
