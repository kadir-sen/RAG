from pathlib import Path

import pytest

from src.vector_runtime import (
    VectorRuntimeCompatibilityError,
    validate_vector_runtime_dependencies,
)


def test_qdrant_runtime_pair_is_pinned() -> None:
    requirements = Path("requirements.txt").read_text(encoding="utf-8")
    assert "qdrant-client==1.18.0" in requirements
    assert "llama-index-vector-stores-qdrant==0.10.2" in requirements


def test_non_qdrant_backend_does_not_import_qdrant() -> None:
    validate_vector_runtime_dependencies("pinecone")


def test_qdrant_runtime_imports_the_real_adapter() -> None:
    try:
        validate_vector_runtime_dependencies("qdrant")
    except VectorRuntimeCompatibilityError as exc:
        pytest.fail(str(exc))
