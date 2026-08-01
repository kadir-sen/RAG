from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.document_rag import DocumentRAG, ProjectScopeRequired, _require_project_id
from src.project_context import set_current_project


def _conditions(filter_obj):
    return {condition.key: condition.match.value for condition in filter_obj.must}


class _Qdrant:
    def __init__(self):
        self.deleted = None
        self.payload_update = None
        self.scrolled = None

    def delete(self, **kwargs):
        self.deleted = kwargs

    def set_payload(self, **kwargs):
        self.payload_update = kwargs

    def scroll(self, **kwargs):
        self.scrolled = kwargs
        return [SimpleNamespace(vector=[0.1, 0.2])], None


def _rag():
    rag = DocumentRAG.__new__(DocumentRAG)
    rag.backend = "qdrant"
    rag.qdrant_client = _Qdrant()
    rag.documents = []
    rag.file_registry = {}
    return rag


def test_vector_access_without_project_fails_closed():
    set_current_project("")
    with pytest.raises(ProjectScopeRequired):
        _require_project_id("")
    with pytest.raises(ProjectScopeRequired):
        _rag().fetch_doc_vectors("same.pdf", project_id="")


def test_same_filename_delete_is_project_and_file_scoped():
    rag = _rag()
    rag._delete_file_vectors(
        "same.pdf", project_id="project-a", file_id="file-a",
    )

    flt = rag.qdrant_client.deleted["points_selector"].filter
    assert _conditions(flt) == {
        "project_id": "project-a",
        "file_id": "file-a",
    }


def test_payload_update_cannot_override_reserved_project_identity():
    rag = _rag()
    assert rag.update_payload_scope(
        "same.pdf",
        {"project_id": "project-b", "doc_type": "contract"},
        project_id="project-a",
        file_id="file-a",
    )

    update = rag.qdrant_client.payload_update
    assert update["payload"]["project_id"] == "project-a"
    assert update["payload"]["file_id"] == "file-a"
    assert _conditions(update["points"].filter) == {
        "project_id": "project-a",
        "file_id": "file-a",
    }


def test_raw_vector_fetch_is_project_and_file_scoped():
    rag = _rag()
    assert rag.fetch_doc_vectors(
        "same.pdf", project_id="project-b", file_id="file-b",
    ) == [[0.1, 0.2]]

    flt = rag.qdrant_client.scrolled["scroll_filter"]
    assert _conditions(flt) == {
        "project_id": "project-b",
        "file_id": "file-b",
    }


def test_metadata_filter_ignores_forged_project_id_and_keeps_server_scope():
    filters = DocumentRAG._build_metadata_filters(
        None,
        None,
        {"project_id": "project-b", "doc_type": "contract"},
        project_id="project-a",
    )
    values = {flt.key: flt.value for flt in filters.filters}
    assert values["project_id"] == "project-a"
    assert values["doc_type"] == "contract"


def test_global_collection_clear_is_disabled():
    with pytest.raises(PermissionError):
        _rag().clear_index()
