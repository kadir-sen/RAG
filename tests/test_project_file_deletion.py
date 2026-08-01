"""Project-scoped deletion coverage for migrated, registry-free corpora."""

from types import SimpleNamespace
import asyncio

from backend.api.files import _delete_legacy_project_file, list_files
from backend.core.projects import ProjectContext
from backend.core.security import UserContext


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _Connection:
    def __init__(self, *, member=True, shared=False):
        self.member = member
        self.shared = shared

    def execute(self, sql, _params):
        if "SELECT DISTINCT doc_id" in sql:
            return _Rows([("doc-1",)] if self.member else [])
        if "project_id<>" in sql:
            return _Rows([(1,)] if self.shared else [])
        raise AssertionError(f"unexpected SQL: {sql}")


def _install_fakes(monkeypatch, tmp_path, *, member=True, shared=False):
    import src.catalog
    import src.chunk_store
    import src.config
    import src.document_rag
    import src.document_registry
    import src.event_timeline

    connection = _Connection(member=member, shared=shared)
    monkeypatch.setattr(src.chunk_store, "get_chunk_store", lambda: SimpleNamespace(connection=lambda: connection))
    monkeypatch.setattr(src.catalog, "get_catalog", lambda: SimpleNamespace(entries={}, remove_entry=lambda *_a, **_k: None))
    cleared = []
    monkeypatch.setattr(
        src.document_rag, "get_document_rag",
        lambda: SimpleNamespace(
            clear_file=lambda name, **kwargs: cleared.append((name, kwargs)),
        ),
    )
    monkeypatch.setattr(src.document_registry, "get_document_registry", lambda: SimpleNamespace(get_all=lambda: []))
    monkeypatch.setattr(src.event_timeline, "get_event_timeline", lambda: SimpleNamespace(delete_by_document=lambda *_a, **_k: 1))
    monkeypatch.setattr(src.config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(src.config, "STORAGE_DIR", tmp_path / "storage")
    return cleared


def test_legacy_delete_requires_selected_project_membership(monkeypatch, tmp_path):
    cleared = _install_fakes(monkeypatch, tmp_path, member=False)

    assert _delete_legacy_project_file("record.pdf", "project-a") is None
    assert cleared == []


def test_legacy_delete_removes_only_project_owned_source(monkeypatch, tmp_path):
    cleared = _install_fakes(monkeypatch, tmp_path)
    source = tmp_path / "data" / "edinburgh_pdfs" / "record.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"pdf")

    result = _delete_legacy_project_file("record.pdf", "project-a")

    assert result is not None
    assert result["source_files_deleted"] == 1
    assert result["shared_source_retained"] is False
    assert not source.exists()
    assert cleared == [("record.pdf", {"project_id": "project-a"})]


def test_legacy_delete_retains_source_referenced_by_another_project(monkeypatch, tmp_path):
    cleared = _install_fakes(monkeypatch, tmp_path, shared=True)
    source = tmp_path / "data" / "edinburgh_pdfs" / "record.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"pdf")

    result = _delete_legacy_project_file("record.pdf", "project-a")

    assert result is not None
    assert result["source_files_deleted"] == 0
    assert result["shared_source_retained"] is True
    assert source.exists()
    assert cleared == [("record.pdf", {"project_id": "project-a"})]


def test_edinburgh_listing_keeps_legacy_inventory_after_new_upload(monkeypatch):
    import backend.api.files as files_api
    from backend.models.responses import FileInfo

    monkeypatch.setattr(files_api._file_service, "list_files", lambda project_id: [{
        "id": "new-id", "name": "new.pdf", "file_type": "document",
        "status": "completed",
    }])
    monkeypatch.setattr(files_api, "_edinburgh_file_infos", lambda project_id: [
        FileInfo(id="old.pdf", name="old.pdf", file_type="document", status="completed"),
    ])
    user = UserContext(
        username="admin2", role="admin", display_name="Admin 2",
        features={"corpus": "edinburgh"}, token_limit=1,
    )
    project = ProjectContext(
        project_id="project-a", name="Edinburgh Tram Inquiry",
        role="owner", embedding_profile="local-bge-v1",
    )

    result = asyncio.run(list_files(user=user, project=project))

    assert {(item.id, item.name) for item in result} == {
        ("old.pdf", "old.pdf"), ("new-id", "new.pdf"),
    }
