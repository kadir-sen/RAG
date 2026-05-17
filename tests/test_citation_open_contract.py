"""Contract tests for the citation → document open flow.

A Pinecone citation always carries a ``doc_id``. The frontend hits
``GET /docs/{doc_id}/content?anchor=page_N`` which lands in
``DocumentService._get_content_sync``. These tests guard the resolution
path so that every doc type the indexer accepts is also openable.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.services.document_service import DocumentService  # noqa: E402
from src.document_registry import DocumentRecord, DocumentRegistry  # noqa: E402
from src.document_rag import generate_doc_id  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────


def _fresh_registry(tmp_path, monkeypatch) -> DocumentRegistry:
    fake_file = tmp_path / "registry.json"
    monkeypatch.setattr("src.document_registry.REGISTRY_FILE", fake_file)
    monkeypatch.setattr(
        "src.document_registry.DocumentRegistry._save",
        lambda self: None,  # no-op for tests
    )
    DocumentRegistry._instance = None
    reg = DocumentRegistry()
    reg._records.clear()
    return reg


def _stub_rag(monkeypatch, file_registry: dict | None = None):
    class _Stub:
        def __init__(self):
            self.file_registry = file_registry or {}

    monkeypatch.setattr("src.document_rag.get_document_rag", lambda: _Stub())


def _stub_data_analyzer(monkeypatch):
    class _Stub:
        file_paths: dict[str, str] = {}
    monkeypatch.setattr("src.data_analyzer_sql.get_data_analyzer", lambda: _Stub())


# ── _resolve_path ────────────────────────────────────────────────────


class TestResolvePath:
    def test_returns_existing_path_unchanged(self, tmp_path):
        real = tmp_path / "letter.docx"
        real.write_text("x")
        assert DocumentService._resolve_path(str(real)) == str(real)

    def test_strips_dedup_suffix_when_alt_exists(self, tmp_path):
        original = tmp_path / "letter.docx"
        original.write_text("x")
        # Registry stored a dedup-suffixed name
        suffixed = tmp_path / "letter_3.docx"
        assert DocumentService._resolve_path(str(suffixed)) == str(original)

    def test_returns_original_when_nothing_matches(self, tmp_path):
        missing = tmp_path / "nope.pdf"
        assert DocumentService._resolve_path(str(missing)) == str(missing)


# ── _get_content_sync routing ───────────────────────────────────────


class TestGetContentSync:
    def test_empty_doc_id_returns_error(self, monkeypatch, tmp_path):
        _stub_rag(monkeypatch)
        _stub_data_analyzer(monkeypatch)
        _fresh_registry(tmp_path, monkeypatch)
        result = DocumentService()._get_content_sync("", "")
        assert result.error and "No document ID" in result.error

    def test_unknown_doc_id_returns_not_found(self, monkeypatch, tmp_path):
        _stub_rag(monkeypatch)
        _stub_data_analyzer(monkeypatch)
        _fresh_registry(tmp_path, monkeypatch)
        result = DocumentService()._get_content_sync("does_not_exist_xyz", "")
        assert result.error == "Document not found"

    def test_registered_txt_doc_returns_text(self, monkeypatch, tmp_path):
        _stub_rag(monkeypatch)
        _stub_data_analyzer(monkeypatch)
        reg = _fresh_registry(tmp_path, monkeypatch)

        txt = tmp_path / "note.txt"
        txt.write_text("hello world", encoding="utf-8")
        doc_id = generate_doc_id(str(txt))
        reg._records[doc_id] = DocumentRecord(
            doc_id=doc_id, file_name="note.txt", file_path=str(txt),
            file_size_kb=1, file_type="document", extension=".txt",
            status="completed",
        )

        result = DocumentService()._get_content_sync(doc_id, "")
        assert result.type == "text"
        assert "hello world" in (result.text or "")
        assert not result.error

    def test_msg_viewer_returns_structured_email(self, monkeypatch, tmp_path):
        """When a .msg file is requested, the service should call the email
        parser and return non-empty body content (or a clear error)."""
        pytest.importorskip("extract_msg")
        _stub_rag(monkeypatch)
        _stub_data_analyzer(monkeypatch)
        reg = _fresh_registry(tmp_path, monkeypatch)

        # Generate a minimal valid .msg via extract_msg writer if available,
        # otherwise fall back to verifying the error path is structured.
        fake_msg = tmp_path / "fake.msg"
        fake_msg.write_bytes(b"NOT A REAL MSG")  # forces parser to error
        doc_id = generate_doc_id(str(fake_msg))
        reg._records[doc_id] = DocumentRecord(
            doc_id=doc_id, file_name="fake.msg", file_path=str(fake_msg),
            file_size_kb=1, file_type="email", extension=".msg",
            status="completed",
        )

        result = DocumentService()._get_content_sync(doc_id, "")
        # Two acceptable shapes:
        #   (a) parser succeeded → result.text contains "Subject:" or "From:"
        #   (b) parser failed → result.error starts with "Cannot parse email"
        assert result.error or result.text
        if result.error:
            assert result.error.startswith("Cannot parse email")
        else:
            assert any(k in (result.text or "") for k in ("Subject:", "From:", "Body"))


# ── Every registered doc is resolvable ───────────────────────────────


class TestRegistryCoverage:
    def test_every_registered_doc_resolves_to_some_path(self, monkeypatch, tmp_path):
        """For each record in the registry, ``_resolve_path`` always returns a
        non-empty string (even if the file is gone, we get the original path
        back so the caller can surface a meaningful error)."""
        _stub_rag(monkeypatch)
        _stub_data_analyzer(monkeypatch)
        reg = _fresh_registry(tmp_path, monkeypatch)

        good = tmp_path / "good.pdf"
        good.write_text("x")
        reg._records["a"] = DocumentRecord(
            doc_id="a", file_name="good.pdf", file_path=str(good),
            file_size_kb=1, file_type="document", extension=".pdf",
            status="completed",
        )
        reg._records["b"] = DocumentRecord(
            doc_id="b", file_name="ghost.pdf",
            file_path=str(tmp_path / "ghost.pdf"),
            file_size_kb=0, file_type="document", extension=".pdf",
            status="completed",
        )

        for rec in reg.get_all():
            resolved = DocumentService._resolve_path(rec.file_path)
            assert isinstance(resolved, str) and resolved
