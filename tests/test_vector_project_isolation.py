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


# ── The notices index is global; the search over it must not be ──────────
#
# LightGraph builds `notices` from graph nodes, which carry no project at all.
# An unscoped search therefore returned other tenants' file names, senders,
# dates and subjects, and those reached the user as the response's
# `related_docs` — observed in production on 2026-08-06, where a project
# holding exactly one uploaded PDF was shown two documents belonging to a
# different corpus.

class _StubGraph:
    """LightGraph with its DuckDB and chunk-store lookups faked out."""

    def __init__(self, rows, scope):
        self._rows = rows
        self._scope = scope
        self._notices_table_ready = True
        self._db = self

    def execute(self, sql, params):  # noqa: D401 - DuckDB stand-in
        return SimpleNamespace(fetchall=lambda: self._rows)

    @staticmethod
    def _project_file_names_factory(scope):
        return staticmethod(lambda project_id: scope.get(project_id))


def _make_graph(rows, scope):
    from src.light_graph import LightGraph

    graph = _StubGraph(rows, scope)
    graph._project_file_names = lambda project_id: scope.get(project_id)
    graph.search_by_topic = LightGraph.search_by_topic.__get__(graph, _StubGraph)
    return graph


_MINE = ("d1", "mine.pdf", "2023-01-01", "s", "r", "subject", "letter", "topics", 2)
_THEIRS = ("d2", "theirs.pdf", "2023-01-02", "s", "r", "subject", "letter", "topics", 2)


def test_notice_search_returns_only_the_active_projects_documents():
    graph = _make_graph([_MINE, _THEIRS], {"p1": {"mine.pdf"}})
    names = [row["file_name"] for row in graph.search_by_topic("subject", project_id="p1")]
    assert names == ["mine.pdf"], "another project's document leaked into related_docs"


def test_notice_search_returns_nothing_without_a_project_scope():
    graph = _make_graph([_MINE, _THEIRS], {})
    set_current_project("")
    assert graph.search_by_topic("subject") == []


def test_notice_search_fails_closed_when_the_scope_lookup_breaks():
    graph = _make_graph([_MINE, _THEIRS], {})
    graph._project_file_names = lambda project_id: None  # lookup failure
    assert graph.search_by_topic("subject", project_id="p1") == []


def test_notice_search_uses_the_request_scoped_project_by_default():
    graph = _make_graph([_MINE, _THEIRS], {"p1": {"mine.pdf"}})
    set_current_project("p1")
    try:
        names = [row["file_name"] for row in graph.search_by_topic("subject")]
        assert names == ["mine.pdf"]
    finally:
        set_current_project("")
