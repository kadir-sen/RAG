"""Tests for DocumentService._resolve_path data/ fallback (Bug 2 regression).

Pinecone vectors store ``file_path`` values from whatever host indexed them
(Windows: ``C:\\projects\\ML_project\\data\\…``; Linux container:
``/app/data/…``). These paths don't exist on the local disk. The resolver
must rescue the file by searching the project's ``data/`` tree by name.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.services.document_service import DocumentService  # noqa: E402
import backend.services.document_service as docsvc  # noqa: E402


@pytest.fixture
def fake_data_root(tmp_path, monkeypatch):
    """Point the resolver's fallback roots at a temp tree we control."""
    documents = tmp_path / "data" / "documents"
    emails = tmp_path / "data" / "emails"
    tables = tmp_path / "data" / "tables"
    for d in (documents, emails, tables):
        d.mkdir(parents=True)
    monkeypatch.setattr(
        docsvc,
        "_DATA_FALLBACK_ROOTS",
        (documents, emails, tables, tmp_path / "data"),
    )
    return tmp_path


class TestResolvePathFallback:
    def test_existing_path_is_returned_unchanged(self, fake_data_root):
        real = fake_data_root / "data" / "documents" / "letter.pdf"
        real.write_bytes(b"x")
        assert DocumentService._resolve_path(str(real)) == str(real)

    def test_strips_dedup_suffix_in_same_dir(self, fake_data_root):
        original = fake_data_root / "data" / "documents" / "letter.pdf"
        original.write_bytes(b"x")
        suffixed = fake_data_root / "data" / "documents" / "letter_3.pdf"
        assert DocumentService._resolve_path(str(suffixed)) == str(original)

    def test_finds_file_by_name_when_stored_path_is_stale_linux_container(
        self, fake_data_root
    ):
        real = fake_data_root / "data" / "documents" / "DPS Letter_TABH.pdf"
        real.write_bytes(b"x")
        stale = "/app/data/documents/DPS Letter_TABH.pdf"
        assert DocumentService._resolve_path(stale) == str(real)

    def test_finds_file_by_name_when_stored_path_is_windows(
        self, fake_data_root
    ):
        real = fake_data_root / "data" / "emails" / "vingcard.msg"
        real.write_bytes(b"x")
        stale = "C:\\projects\\ML_project\\data\\emails\\vingcard.msg"
        assert DocumentService._resolve_path(stale) == str(real)

    def test_searches_all_data_subdirs(self, fake_data_root):
        # File hidden in a deep subdir of tables/
        deep = fake_data_root / "data" / "tables" / "nested" / "report.xlsx"
        deep.parent.mkdir(parents=True)
        deep.write_bytes(b"x")
        stale = "/app/data/tables/report.xlsx"
        assert DocumentService._resolve_path(stale) == str(deep)

    def test_returns_original_when_nothing_matches(self, fake_data_root):
        missing = "/app/data/documents/never_existed.pdf"
        assert DocumentService._resolve_path(missing) == missing

    def test_empty_path_passes_through(self, fake_data_root):
        assert DocumentService._resolve_path("") == ""

    def test_dedup_suffix_fallback_finds_clean_name_under_data_root(
        self, fake_data_root
    ):
        """Both transforms together: dedup-suffix removal + data-root search."""
        real = fake_data_root / "data" / "documents" / "memo.docx"
        real.write_bytes(b"x")
        stale = "/somewhere/else/memo_5.docx"
        assert DocumentService._resolve_path(stale) == str(real)
