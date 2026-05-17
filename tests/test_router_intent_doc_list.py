"""Tests that confirm `_handle_file_list_query` routes to the new behavior:

  - default + "briefly list ..." → grouped summary
  - "verbose" / "all files" → flat list
  - "how many ..." → stats path with by-type breakdown
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.document_registry import DocumentRecord, DocumentRegistry  # noqa: E402
from src.router import QueryRouter  # noqa: E402


def _make_router() -> QueryRouter:
    router = QueryRouter.__new__(QueryRouter)
    router.document_rag = None
    router.data_analyzer = None
    router._jargon = None
    router._hybrid_executor = None
    router._schema_alias_cache = {}
    return router


def _record(name: str, ext: str, file_type: str, kb: int = 0) -> DocumentRecord:
    return DocumentRecord(
        doc_id=f"id_{name}",
        file_name=name,
        file_path=f"/tmp/{name}",
        file_size_kb=kb,
        file_type=file_type,
        extension=ext,
        status="completed",
    )


@pytest.fixture
def populated_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.document_registry.REGISTRY_FILE", tmp_path / "registry.json"
    )
    monkeypatch.setattr(
        "src.document_registry.DocumentRegistry._save", lambda self: None,
    )
    DocumentRegistry._instance = None
    reg = DocumentRegistry()
    reg._records.clear()
    # 3 emails, 2 PDFs, 2 Excels
    samples = [
        _record("a.msg", ".msg", "email"),
        _record("b.msg", ".msg", "email"),
        _record("c.eml", ".eml", "email"),
        _record("doc1.pdf", ".pdf", "document", kb=200),
        _record("doc2.pdf", ".pdf", "document", kb=300),
        _record("data1.xlsx", ".xlsx", "data", kb=20),
        _record("data2.xlsx", ".xlsx", "data", kb=22),
    ]
    for rec in samples:
        reg._records[rec.doc_id] = rec
    return reg


class TestFileListRouting:
    def test_briefly_list_returns_grouped_summary(self, populated_registry):
        router = _make_router()
        result = router._handle_file_list_query("Briefly list the document types you have")

        ans = result["answer"]
        assert "Correspondence" in ans
        assert "Documents" in ans
        assert "Spreadsheets" in ans
        # Per-file lines must NOT be present (no leading "1. ", "2. ", etc.)
        for n in range(1, 10):
            assert f"\n{n}. " not in ans

    def test_default_list_query_also_grouped(self, populated_registry):
        result = _make_router()._handle_file_list_query("list documents")
        ans = result["answer"]
        assert "Correspondence" in ans or "Documents" in ans
        assert "verbose" in ans.lower()

    def test_verbose_query_returns_flat_list(self, populated_registry):
        result = _make_router()._handle_file_list_query("list all files verbose")
        ans = result["answer"]
        # Each file appears as a numbered line
        for name in ("a.msg", "doc1.pdf", "data1.xlsx"):
            assert name in ans
        # Numbered entries are present
        assert "1. " in ans

    def test_how_many_query_returns_stats(self, populated_registry, monkeypatch):
        # Stub light_graph so it doesn't try to load real graph data
        class _Graph:
            def get_document_stats(self):
                return {"total_documents": 0, "total_edges": 0}
        monkeypatch.setattr("src.light_graph.get_light_graph", lambda: _Graph())

        result = _make_router()._handle_file_list_query(
            "How many documents do you have?"
        )
        ans = result["answer"]
        assert "Document Library Overview" in ans
        assert "Total files:" in ans

    def test_grouped_count_matches_dedupe(self, tmp_path, monkeypatch):
        """Two registry rows for the same .xlsx must count as one in the grouped
        summary."""
        monkeypatch.setattr(
            "src.document_registry.REGISTRY_FILE", tmp_path / "registry.json"
        )
        monkeypatch.setattr(
            "src.document_registry.DocumentRegistry._save", lambda self: None
        )
        DocumentRegistry._instance = None
        reg = DocumentRegistry()
        reg._records.clear()
        # Same file, two doc_ids (the pre-fix duplicate pattern).
        reg._records["legacy_a"] = DocumentRecord(
            doc_id="legacy_a", file_name="Equipment Log 2.xlsx",
            file_path="/tmp/Equipment Log 2.xlsx", file_size_kb=18,
            file_type="data", extension=".xlsx", status="completed",
            table_names=["direct_equipment_log"],
        )
        reg._records["legacy_b"] = DocumentRecord(
            doc_id="legacy_b", file_name="Equipment Log 2.xlsx",
            file_path="/tmp/Equipment Log 2.xlsx", file_size_kb=0,
            file_type="data", extension=".xlsx", status="completed",
            table_names=["t_equipment_log_2_sheet1_a9cfbc"],
        )

        result = _make_router()._handle_file_list_query("briefly list")
        ans = result["answer"]
        # Even though there are 2 registry rows, the grouped summary reports 1.
        assert "Found 1 unique file(s):" in ans
        assert "Spreadsheets:** 1" in ans
