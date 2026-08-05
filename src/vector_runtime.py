"""Fail-fast compatibility checks for the configured vector backend."""

from __future__ import annotations


class VectorRuntimeCompatibilityError(RuntimeError):
    """The configured vector backend cannot be imported safely."""


def validate_vector_runtime_dependencies(backend: str | None = None) -> None:
    """Validate imports needed by the selected vector backend.

    Importing the top-level distributions is not enough: incompatible releases
    can both be installed successfully and still fail inside the LlamaIndex
    adapter. Import the exact classes used by ``DocumentRAG`` so CI, image build
    and runtime health all exercise the same compatibility boundary.
    """

    if backend is None:
        from .config import VECTOR_STORE_BACKEND

        backend = VECTOR_STORE_BACKEND

    if str(backend).lower() != "qdrant":
        return

    try:
        from qdrant_client import QdrantClient  # noqa: F401
        from qdrant_client.http import models as qmodels  # noqa: F401
        from llama_index.vector_stores.qdrant import QdrantVectorStore  # noqa: F401
    except (ImportError, AttributeError) as exc:
        raise VectorRuntimeCompatibilityError(
            "The Qdrant client and LlamaIndex Qdrant adapter are unavailable "
            f"or incompatible ({type(exc).__name__}: {exc})."
        ) from exc


__all__ = ["VectorRuntimeCompatibilityError", "validate_vector_runtime_dependencies"]
