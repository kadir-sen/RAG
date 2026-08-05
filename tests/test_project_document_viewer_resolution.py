"""Project-scoped regression tests for citation document rendering.

The deployed Edinburgh corpus stores project membership in chunks/catalogs,
while its source paths can point at the machine that originally indexed it.
The viewer must recover those sources on the current host without turning a
filename into a cross-project access primitive.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backend.services.document_service as document_module
from backend.models.responses import DocContent
from backend.services.document_service import DocumentService, _clean_table_rows
from src.document_rag import generate_doc_id


class _Registry:
    def __init__(self, records=()):
        self.records = list(records)

    def get_all(self, project_id=None):
        return [r for r in self.records if r.project_id == project_id]


class _Connection:
    def __init__(self, rows_by_project=None):
        self.rows_by_project = rows_by_project or {}

    def execute(self, _query, params):
        return SimpleNamespace(fetchall=lambda: self.rows_by_project.get(params[0], []))


@pytest.fixture
def viewer(tmp_path, monkeypatch):
    shared = tmp_path / "data" / "shared-corpus"
    shared.mkdir(parents=True)
    monkeypatch.setattr(document_module, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(document_module, "_SHARED_CORPUS_ROOTS", (shared,))
    monkeypatch.setattr(
        "src.document_registry.get_document_registry", lambda: _Registry(),
    )
    monkeypatch.setattr(
        "src.catalog.get_catalog", lambda: SimpleNamespace(entries={}),
    )
    monkeypatch.setattr(
        "src.document_rag.get_document_rag",
        lambda: SimpleNamespace(file_registry={}),
    )
    monkeypatch.setattr(
        "src.chunk_store.get_chunk_store",
        lambda: SimpleNamespace(connection=lambda: _Connection()),
    )
    return DocumentService(), shared


def test_project_chunk_membership_opens_real_shared_pdf(viewer, monkeypatch):
    service, shared = viewer
    pdf = shared / "CEC00381196_PART1.pdf"
    pdf.write_bytes(b"pdf")
    rows = [(pdf.name, 5, "citation text")]
    monkeypatch.setattr(
        "src.chunk_store.get_chunk_store",
        lambda: SimpleNamespace(connection=lambda: _Connection({"project-a": rows})),
    )
    monkeypatch.setattr(
        service, "_serve_by_extension",
        lambda path, anchor="": (Path(path), anchor),
    )

    path, anchor = service._get_content_sync(
        "dead-ingest-id", "page_5", pdf.name, "project-a",
    )

    assert path == pdf
    assert anchor == "page_5"


def test_shared_file_name_without_project_membership_is_rejected(viewer):
    service, shared = viewer
    (shared / "SECRET.pdf").write_bytes(b"pdf")

    result = service._get_content_sync(
        "guessed-id", "page_1", "SECRET.pdf", "project-b",
    )

    assert result.error == "Document not found"


def test_project_chunk_cannot_cross_into_another_private_project(viewer, monkeypatch):
    service, _shared = viewer
    private = document_module._PROJECT_ROOT / "data" / "projects" / "project-b"
    private.mkdir(parents=True)
    (private / "PRIVATE.pdf").write_bytes(b"pdf")
    rows = [("PRIVATE.pdf", 2, "permitted excerpt only")]
    monkeypatch.setattr(
        "src.chunk_store.get_chunk_store",
        lambda: SimpleNamespace(connection=lambda: _Connection({"project-a": rows})),
    )

    result = service._get_content_sync(
        "chunk-id", "page_2", "PRIVATE.pdf", "project-a",
    )

    assert result.type == "text"
    assert result.text == "permitted excerpt only"


def test_project_catalog_recovers_excel_from_stale_ingest_path(viewer, monkeypatch):
    service, shared = viewer
    excel_dir = shared / "excels"
    excel_dir.mkdir()
    excel = excel_dir / "CEC00115697.xls"
    excel.write_bytes(b"excel")
    stale = r"C:\Users\indexer\edinburgh_tram\excels\CEC00115697.xls"
    entry = SimpleNamespace(
        project_id="project-a", source_type="excel", source_file=stale, tables=[],
    )
    monkeypatch.setattr(
        "src.catalog.get_catalog", lambda: SimpleNamespace(entries={"one": entry}),
    )
    monkeypatch.setattr(
        service, "_serve_by_extension", lambda path, anchor="": Path(path),
    )

    result = service._get_content_sync(
        generate_doc_id(stale), "", excel.name, "project-a",
    )

    assert result == excel


def test_catalog_entry_from_another_project_is_not_opened(viewer, monkeypatch):
    service, shared = viewer
    excel = shared / "ONLY-B.xlsx"
    excel.write_bytes(b"excel")
    entry = SimpleNamespace(
        project_id="project-b", source_type="excel",
        source_file="/old/host/ONLY-B.xlsx", tables=[],
    )
    monkeypatch.setattr(
        "src.catalog.get_catalog", lambda: SimpleNamespace(entries={"one": entry}),
    )

    result = service._get_content_sync(
        generate_doc_id(entry.source_file), "", excel.name, "project-a",
    )

    assert result.error == "Document not found"


def test_spreadsheet_rows_are_json_safe_for_fastapi_response():
    """DuckDB/pandas scalars must not fail during response serialization."""
    np = pytest.importorskip("numpy")
    pd = pytest.importorskip("pandas")
    rows = _clean_table_rows([{
        "date": pd.Timestamp("2026-08-05T12:30:00"),
        "count": np.int64(7),
        "ratio": np.float64(1.25),
        "missing": pd.NaT,
    }])

    payload = json.loads(DocContent(type="table", rows=rows).model_dump_json())

    assert payload["rows"] == [{
        "date": "2026-08-05T12:30:00",
        "count": 7,
        "ratio": 1.25,
        "missing": None,
    }]


def test_excel_source_anchor_opens_exact_sheet_and_row_range(tmp_path):
    pd = pytest.importorskip("pandas")
    path = tmp_path / "progress.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"Period": list(range(1, 81)), "Progress": list(range(101, 181))}).to_excel(
            writer, sheet_name="Period 01", index=False,
        )

    result = DocumentService()._serve_excel_file(
        str(path), "sheet_Period 01_rows_42_45",
    )

    assert result.error is None
    assert result.sheet_name == "Period 01"
    assert (result.row_from, result.row_to) == (42, 45)
    assert [row["Period"] for row in result.rows] == [41, 42, 43, 44]
