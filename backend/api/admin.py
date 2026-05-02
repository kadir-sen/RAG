"""Admin endpoints for diagnosing and repairing the SQL data-tables pipeline.

These endpoints address the failure mode where Excel/CSV files are present in
the document registry but never registered as DuckDB tables (catalog/parquets
empty), so SQL questions return 'No data tables loaded'.

Endpoints:
  GET  /api/admin/data-tables/status      → counts + per-file registration state
  POST /api/admin/data-tables/reindex     → re-process selected (or all unregistered) files
  POST /api/admin/data-tables/diagnose    → per-sheet schema match preview for one file
"""
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

router = APIRouter()


# ── Request/response models ─────────────────────────────────

class ReindexRequest(BaseModel):
    file_ids: Optional[List[str]] = None  # None → all data files needing reindex
    dry_run: bool = False


class DiagnoseRequest(BaseModel):
    file_id: str


class FileStatus(BaseModel):
    file_id: str
    file_name: str
    extension: str
    status: str
    data_table_status: Optional[str] = None
    data_tables_count: int = 0
    table_names: List[str] = Field(default_factory=list)


class StatusResponse(BaseModel):
    total_data_files: int
    registered: int
    no_schema_match: int
    error: int
    pending: int
    duckdb_tables_loaded: int
    catalog_entries: int
    parquet_files: int
    schema_summary: dict
    files: List[FileStatus]


# ── Helpers ─────────────────────────────────────────────────

def _is_data_extension(ext: str) -> bool:
    return ext.lower() in (".xlsx", ".xls", ".csv")


def _get_data_records():
    from src.document_registry import get_document_registry
    registry = get_document_registry()
    return [r for r in registry.get_all() if _is_data_extension(r.extension)]


# ── GET status ──────────────────────────────────────────────

@router.get("/admin/data-tables/status", response_model=StatusResponse)
async def data_tables_status() -> StatusResponse:
    from pathlib import Path as _Path
    from src.catalog import get_catalog, PARQUET_DIR
    from src.data_analyzer_sql import get_data_analyzer

    catalog = get_catalog()

    # Build a fast lookup of which files are present in the catalog so we can
    # treat catalog membership as the source of truth for "registered" — older
    # uploads predate the data_table_status field on DocumentRecord.
    catalog_files: dict[str, int] = {}
    for entry in catalog.entries.values():
        fname = _Path(entry.source_file).name
        catalog_files[fname] = len(entry.tables)

    records = _get_data_records()
    files: list[FileStatus] = []
    for r in records:
        status = getattr(r, "data_table_status", None)
        tables_count = getattr(r, "data_tables_count", 0)
        # Backfill when registry was written before data_table_status existed
        if status is None and r.file_name in catalog_files:
            status = "registered"
            tables_count = catalog_files[r.file_name] or tables_count
        files.append(FileStatus(
            file_id=r.doc_id,
            file_name=r.file_name,
            extension=r.extension,
            status=r.status,
            data_table_status=status,
            data_tables_count=tables_count,
            table_names=list(getattr(r, "table_names", []) or []),
        ))

    counts = {"registered": 0, "no_schema_match": 0, "error": 0, "pending": 0}
    for f in files:
        s = f.data_table_status
        if s == "registered":
            counts["registered"] += 1
        elif s == "no_schema_match":
            counts["no_schema_match"] += 1
        elif s == "error":
            counts["error"] += 1
        else:
            counts["pending"] += 1

    # Schema breakdown from catalog (target_schema is set per TableMetadata)
    schema_summary: dict[str, int] = {}
    for entry in catalog.entries.values():
        for t in entry.tables:
            sid = (
                getattr(t, "target_schema", None)
                or getattr(t, "extraction_method", None)
                or "unknown"
            )
            schema_summary[sid] = schema_summary.get(sid, 0) + 1

    # Live DuckDB count
    try:
        analyzer = get_data_analyzer()
        duckdb_loaded = len(analyzer.list_tables())
    except Exception:
        duckdb_loaded = 0

    # Parquet files on disk — use the canonical PARQUET_DIR from catalog.py
    parquet_count = 0
    if PARQUET_DIR.exists():
        parquet_count = sum(1 for _ in PARQUET_DIR.glob("*.parquet"))

    return StatusResponse(
        total_data_files=len(files),
        registered=counts["registered"],
        no_schema_match=counts["no_schema_match"],
        error=counts["error"],
        pending=counts["pending"],
        duckdb_tables_loaded=duckdb_loaded,
        catalog_entries=len(catalog.entries),
        parquet_files=parquet_count,
        schema_summary=schema_summary,
        files=files,
    )


# ── POST reindex ─────────────────────────────────────────────

def _reindex_files_background(targets: list[tuple[str, str]]):
    """Run inside a BackgroundTask. targets: [(file_id, file_path), ...]"""
    from src.file_router import delete_document
    from src.document_rag import generate_doc_id
    from backend.tasks.indexing import index_file_background

    for file_id, file_path in targets:
        try:
            delete_document(file_id)
            if not Path(file_path).exists():
                continue
            new_id = generate_doc_id(file_path)
            # Run synchronously in this task; we already are in background
            index_file_background(new_id, file_path)
        except Exception:
            # Best-effort backfill: keep going on failure
            continue


@router.post("/admin/data-tables/reindex")
async def reindex_data_tables(req: ReindexRequest, background_tasks: BackgroundTasks):
    """Re-process Excel/CSV files through the ingestion pipeline so they end up
    in the catalog and DuckDB. Defaults to every data file whose
    data_table_status is not 'registered'."""
    from src.schema_converter import get_format_converter

    records = _get_data_records()

    # Filter
    if req.file_ids:
        wanted = set(req.file_ids)
        targets = [r for r in records if r.doc_id in wanted]
    else:
        targets = [
            r for r in records
            if getattr(r, "data_table_status", None) != "registered"
        ]

    if req.dry_run:
        converter = get_format_converter()
        previews = []
        for r in targets:
            if not Path(r.file_path).exists():
                previews.append({
                    "file_id": r.doc_id,
                    "file_name": r.file_name,
                    "would_register": False,
                    "reason": "file_missing",
                    "schema_matches": [],
                })
                continue
            try:
                conv_results = converter.process_excel(r.file_path)
                matches = [
                    {
                        "sheet": cr.sheet_name,
                        "schema_id": cr.target_schema,
                        "rows": int(len(cr.df)) if cr.df is not None else 0,
                    }
                    for cr in conv_results if cr.success and cr.df is not None
                ]
                previews.append({
                    "file_id": r.doc_id,
                    "file_name": r.file_name,
                    "would_register": bool(matches),
                    "reason": None if matches else "no_schema_match",
                    "schema_matches": matches,
                })
            except Exception as e:
                previews.append({
                    "file_id": r.doc_id,
                    "file_name": r.file_name,
                    "would_register": False,
                    "reason": f"error: {e}",
                    "schema_matches": [],
                })
        return {
            "dry_run": True,
            "total_targets": len(targets),
            "would_register": sum(1 for p in previews if p["would_register"]),
            "previews": previews,
        }

    # Real run — schedule backfill as one BackgroundTask
    pairs = [(r.doc_id, r.file_path) for r in targets]
    background_tasks.add_task(_reindex_files_background, pairs)
    return {
        "dry_run": False,
        "scheduled": len(pairs),
        "files": [r.file_name for r in targets],
    }


# ── POST diagnose ────────────────────────────────────────────

@router.post("/admin/data-tables/diagnose")
async def diagnose_data_table(req: DiagnoseRequest):
    """Detailed schema-match breakdown for one Excel/CSV file."""
    from src.document_registry import get_document_registry
    from src.schema_converter import get_target_schemas
    from src.extractors import match_extractor
    import pandas as pd

    rec = get_document_registry().get(req.file_id)
    if not rec:
        return {"ok": False, "error": "file not found"}
    if not _is_data_extension(rec.extension):
        return {"ok": False, "error": "not a data file"}
    if not Path(rec.file_path).exists():
        return {"ok": False, "error": "file missing on disk"}

    schemas = get_target_schemas()
    schema_objs = [schemas.get_schema(s["schema_id"]) for s in schemas.list_schemas()]
    schema_objs = [s for s in schema_objs if s]

    # Read sheets
    ext = rec.extension.lower()
    sheets: dict = {}
    try:
        if ext == ".csv":
            sheets = {"Sheet1": pd.read_csv(rec.file_path)}
        else:
            xls = pd.ExcelFile(rec.file_path)
            for s in xls.sheet_names:
                try:
                    df = pd.read_excel(rec.file_path, sheet_name=s)
                    if not df.empty:
                        sheets[s] = df
                except Exception as e:
                    sheets[s] = e  # type: ignore
    except Exception as e:
        return {"ok": False, "error": f"cannot open: {e}"}

    sheet_reports = []
    for sheet_name, df in sheets.items():
        if isinstance(df, Exception):
            sheet_reports.append({"sheet": sheet_name, "error": str(df)})
            continue
        df_cols = {str(c).lower().strip() for c in df.columns}
        per_schema = []
        for schema in schema_objs:
            required = [c for c in schema.columns if c.required]
            matched, missing = [], []
            for col in required:
                if col.name.lower() in df_cols or any(
                    a.lower() in df_cols for a in col.aliases
                ):
                    matched.append(col.name)
                else:
                    missing.append(col.name)
            per_schema.append({
                "schema_id": schema.schema_id,
                "matched": matched,
                "missing": missing,
                "ratio": round(len(matched) / max(len(required), 1), 3),
            })
        best = max(per_schema, key=lambda r: r["ratio"]) if per_schema else None
        sheet_reports.append({
            "sheet": sheet_name,
            "rows": int(len(df)),
            "columns": [str(c) for c in df.columns],
            "schema_matches": per_schema,
            "best_schema": best["schema_id"] if best and best["ratio"] >= 0.7 else None,
            "best_ratio": best["ratio"] if best else 0.0,
        })

    return {
        "ok": True,
        "file": {
            "id": rec.doc_id,
            "name": rec.file_name,
            "extension": rec.extension,
            "data_table_status": getattr(rec, "data_table_status", None),
        },
        "extractor_matches": match_extractor(rec.file_path),
        "sheets": sheet_reports,
    }
