"""Tests for the file-list dedupe + grouped-summary behavior.

Covers:
  - DocumentRegistry.hydrate_from_existing collapses multiple catalog rows
    that share the same source_file into one record.
  - QueryRouter._dedupe_records and _categorize_record helpers.
  - Grouped summary vs verbose flat list rendering.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.catalog import CatalogEntry, TableMetadata  # noqa: E402
from src.document_registry import DocumentRecord, DocumentRegistry  # noqa: E402
from src.router import QueryRouter  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────


def _fresh_registry(tmp_path, monkeypatch) -> DocumentRegistry:
    """Build a brand-new DocumentRegistry singleton pointing at a temp file."""
    fake_file = tmp_path / "registry.json"
    monkeypatch.setattr("src.document_registry.REGISTRY_FILE", fake_file)
    # Prevent GCS sync side effect during tests
    monkeypatch.setattr(
        "src.document_registry.DocumentRegistry._save",
        lambda self: fake_file.write_text(
            __import__("json").dumps({k: __import__("dataclasses").asdict(v)
                                      for k, v in self._records.items()}),
            encoding="utf-8",
        ),
    )
    # Reset singleton
    DocumentRegistry._instance = None
    reg = DocumentRegistry()
    reg._records.clear()
    return reg


def _table(table_name: str, table_id: str = "tid") -> TableMetadata:
    return TableMetadata(
        table_id=table_id,
        source_file="",
        source_type="excel",
        table_name=table_name,
        parquet_path="",
    )


def _make_router() -> QueryRouter:
    """QueryRouter instance that bypasses external setup."""
    router = QueryRouter.__new__(QueryRouter)
    router.document_rag = None
    router.data_analyzer = None
    router._jargon = None
    router._hybrid_executor = None
    router._schema_alias_cache = {}
    return router


def _record(name: str, ext: str, file_type: str, kb: int = 0,
            tables=None, file_path: str = "") -> DocumentRecord:
    return DocumentRecord(
        doc_id=f"id_{name}",
        file_name=name,
        file_path=file_path or f"/tmp/{name}",
        file_size_kb=kb,
        file_type=file_type,
        extension=ext,
        status="completed",
        table_names=list(tables or []),
    )


# ── Hydrate dedupe ───────────────────────────────────────────────────


class TestHydrateDedup:
    def test_same_xlsx_two_catalog_entries_collapses_to_one(self, tmp_path, monkeypatch):
        reg = _fresh_registry(tmp_path, monkeypatch)

        source = "/tmp/Equipment Log 2.xlsx"
        schema_entry = CatalogEntry(
            source_file=source, source_type="excel", file_hash="h1",
            tables=[_table("direct_equipment_log", "tid1")],
        )
        raw_entry = CatalogEntry(
            source_file=source, source_type="excel", file_hash="h1",
            tables=[_table("t_equipment_log_2_sheet1_a9cfbc", "tid2")],
        )

        reg.hydrate_from_existing(
            rag_registry={},
            catalog_entries={"k1": schema_entry, "k2": raw_entry},
        )

        records = [r for r in reg.get_all() if r.file_name == "Equipment Log 2.xlsx"]
        assert len(records) == 1, f"expected 1 record, got {len(records)}"
        rec = records[0]
        assert set(rec.table_names) == {
            "direct_equipment_log",
            "t_equipment_log_2_sheet1_a9cfbc",
        }
        assert rec.extension == ".xlsx"
        assert rec.file_type == "data"

    def test_collapse_legacy_duplicates_keeps_canonical_doc_id(
        self, tmp_path, monkeypatch
    ):
        reg = _fresh_registry(tmp_path, monkeypatch)
        # Two pre-fix records sharing the same file (different doc_ids).
        from src.document_rag import generate_doc_id

        path = "/tmp/Manpower Log.xlsx"
        canonical = generate_doc_id(path)
        legacy_id = "legacy_hash_abc"
        reg._records[legacy_id] = DocumentRecord(
            doc_id=legacy_id, file_name="Manpower Log.xlsx", file_path=path,
            file_size_kb=0, file_type="data", extension=".xlsx",
            status="completed", table_names=["t_legacy"],
        )
        reg._records[canonical] = DocumentRecord(
            doc_id=canonical, file_name="Manpower Log.xlsx", file_path=path,
            file_size_kb=55, file_type="data", extension=".xlsx",
            status="completed", table_names=["direct_manpower"],
        )

        collapsed = reg._collapse_legacy_duplicates_locked()
        assert collapsed == 1
        records = reg.get_all()
        assert len(records) == 1
        rec = records[0]
        assert rec.doc_id == canonical
        assert "t_legacy" in rec.table_names
        assert "direct_manpower" in rec.table_names
        assert rec.file_size_kb == 55  # richer metadata kept


# ── Router rendering helpers ─────────────────────────────────────────


class TestDedupRecords:
    def test_collapses_by_file_name_and_path(self):
        a = _record("X.xlsx", ".xlsx", "data", kb=18, tables=["t1"])
        b = _record("X.xlsx", ".xlsx", "data", kb=0, tables=["t2"])
        result = QueryRouter._dedupe_records([a, b])
        assert len(result) == 1
        # Keeper is the one with the larger file_size_kb
        assert result[0].file_size_kb == 18

    def test_keeps_distinct_files(self):
        a = _record("A.pdf", ".pdf", "document")
        b = _record("B.pdf", ".pdf", "document")
        result = QueryRouter._dedupe_records([a, b])
        assert {r.file_name for r in result} == {"A.pdf", "B.pdf"}


class TestCategorize:
    @pytest.mark.parametrize("ext,file_type,expected", [
        (".msg", "email", "correspondence"),
        (".eml", "email", "correspondence"),
        (".pdf", "document", "documents"),
        (".docx", "document", "documents"),
        (".doc", "document", "documents"),
        (".txt", "document", "documents"),
        (".xlsx", "data", "spreadsheets"),
        (".xls", "data", "spreadsheets"),
        (".csv", "data", "spreadsheets"),
        (".zip", "", "other"),
    ])
    def test_categorize_by_extension(self, ext, file_type, expected):
        rec = _record(f"f{ext}", ext, file_type)
        assert QueryRouter._categorize_record(rec) == expected


class TestGroupedSummary:
    def test_grouped_summary_counts_match_categories(self):
        records = [
            _record("a.msg", ".msg", "email"),
            _record("b.msg", ".msg", "email"),
            _record("c.eml", ".eml", "email"),
            _record("d.pdf", ".pdf", "document"),
            _record("e.docx", ".docx", "document"),
            _record("f.xlsx", ".xlsx", "data"),
            _record("g.xlsx", ".xlsx", "data"),
            _record("h.csv", ".csv", "data"),
        ]
        router = _make_router()
        answer = router._render_grouped_file_summary(records)

        assert "Found 8 unique file(s):" in answer
        assert "Correspondence (emails):** 3" in answer
        assert "Documents:** 2" in answer
        assert "Spreadsheets:** 3" in answer
        # Sub-format breakdown shows up
        assert "Outlook .msg" in answer
        assert "Excel" in answer
        assert "CSV" in answer
        # Hint about verbose mode is visible
        assert "verbose" in answer.lower()

    def test_grouped_summary_skips_empty_categories(self):
        records = [_record("only.pdf", ".pdf", "document")]
        answer = _make_router()._render_grouped_file_summary(records)
        assert "Documents:** 1" in answer
        assert "Correspondence" not in answer
        assert "Spreadsheets" not in answer

    def test_grouped_summary_is_short(self):
        """A 107-row registry must not produce a 107-line output."""
        records = [_record(f"file_{i}.pdf", ".pdf", "document") for i in range(107)]
        answer = _make_router()._render_grouped_file_summary(records)
        line_count = len(answer.splitlines())
        # Header + 1 category line + blank + hint = ~5 lines, well under 15
        assert line_count < 15


class TestVerboseList:
    def test_verbose_groups_by_category_and_lists_all(self):
        records = [
            _record("a.msg", ".msg", "email"),
            _record("b.pdf", ".pdf", "document"),
            _record("c.xlsx", ".xlsx", "data", tables=["t1", "t2"]),
        ]
        answer = _make_router()._render_verbose_file_list(records)
        assert "Found 3 unique file(s):" in answer
        assert "Correspondence (1):" in answer
        assert "Documents (1):" in answer
        assert "Spreadsheets (1):" in answer
        assert "a.msg" in answer
        assert "b.pdf" in answer
        assert "c.xlsx" in answer
        assert "2 tables" in answer
