"""File upload, listing, deletion, stats, and export endpoints."""

import os
from typing import List

from fastapi import APIRouter, UploadFile, File, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse

from backend.core.security import get_current_user, UserContext
from backend.models.responses import FileInfo, UploadResult
from backend.services.file_service import FileService
from backend.tasks.indexing import index_file_background

router = APIRouter()
_file_service = FileService()


def _edinburgh_data_table_infos() -> List[FileInfo]:
    """FileInfo rows for the edinburgh corpus's SQL data tables (Excel/CSV), read
    from the catalog by corpus tag. These live as DuckDB/parquet tables (not in the
    chunk store), so without this they never reach the 'edinburgh' Spreadsheets list.
    doc_id == generate_doc_id(source_file) so the viewer resolves them via the
    registry → direct file render. Read-only."""
    from src.catalog import get_catalog
    from src.document_rag import generate_doc_id
    out: List[FileInfo] = []
    for entry in get_catalog().entries.values():
        if (getattr(entry, "corpus", "demo") or "demo").lower() != "edinburgh":
            continue
        if entry.source_type not in ("excel", "csv"):
            continue
        fname = os.path.basename(entry.source_file)
        cols = list(entry.tables[0].columns or [])[:8] if entry.tables else []
        out.append(FileInfo(
            id=generate_doc_id(entry.source_file),
            name=fname,
            file_type="data",
            tables=len(entry.tables),
            rows=sum(t.row_count for t in entry.tables),
            status="completed",
            data_table_status="registered",
            data_tables_count=len(entry.tables),
            columns=cols,
            sheets=len(entry.tables),
        ))
    return out


def _edinburgh_file_infos() -> List[FileInfo]:
    """FileInfo rows for the 'edinburgh' account: bulk vectors-only PDFs/emails
    (chunk-store docs not in the registry) PLUS its SQL data tables (Excel/CSV)
    from the catalog, so Documents AND Spreadsheets both reflect its own corpus.
    Read-only."""
    from src.document_registry import get_document_registry
    from src.chunk_store import get_chunk_store
    reg_names = {r.file_name for r in get_document_registry().get_completed()}
    con = get_chunk_store().connection()
    rows = con.execute(
        "SELECT file_name, MAX(page_number) FROM chunks "
        "WHERE file_name IS NOT NULL AND file_name <> '' GROUP BY file_name"
    ).fetchall()
    out: List[FileInfo] = []
    for file_name, max_page in rows:
        if file_name in reg_names:
            continue
        ext = os.path.splitext(file_name)[1].lower()
        ftype = ("email" if ext in (".eml", ".msg")
                 else "data" if ext in (".xlsx", ".xls", ".csv") else "document")
        try:
            pages = int(max_page) if max_page else None
        except (TypeError, ValueError):
            pages = None
        out.append(FileInfo(id=file_name, name=file_name, file_type=ftype,
                            pages=pages, status="completed"))
    # Merge the edinburgh SQL data tables (Excel/CSV) — these are not in the chunk store.
    try:
        out.extend(_edinburgh_data_table_infos())
    except Exception:
        pass
    return out


@router.post("/upload", response_model=UploadResult)
async def upload_file(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    user: UserContext = Depends(get_current_user),
):
    saved_path, file_id, is_duplicate = await _file_service.save(file)
    if is_duplicate:
        return UploadResult(
            file_id=file_id,
            filename=file.filename,
            status="completed",
        )
    # Propagate the uploader's corpus so the background indexer tags new data
    # tables correctly (otherwise the unset ContextVar defaults them to 'demo'
    # and an edinburgh user's upload would silently land in the demo corpus).
    try:
        corpus = str((user.features or {}).get("corpus") or "").lower()
    except Exception:
        corpus = ""
    background_tasks.add_task(index_file_background, file_id, saved_path, corpus)
    return UploadResult(
        file_id=file_id,
        filename=file.filename,
        status="indexing",
    )


@router.get("/files", response_model=List[FileInfo])
async def list_files(user: UserContext = Depends(get_current_user)):
    # Per-user corpus split: the 'edinburgh' account's counts/lists come from the
    # bulk vectors-only set; everyone else from the registry (demo) files.
    try:
        if str((user.features or {}).get("corpus") or "").lower() == "edinburgh":
            return _edinburgh_file_infos()
    except Exception:
        pass
    raw = _file_service.list_files(corpus="demo")
    return [
        FileInfo(
            id=f.get("id", ""),
            name=f.get("name", ""),
            file_type=f.get("file_type", ""),
            pages=f.get("pages"),
            ocr_pages=f.get("ocr_pages", 0),
            tables=f.get("tables", 0),
            rows=f.get("rows", 0),
            status=f.get("status", "completed"),
            data_table_status=f.get("data_table_status"),
            data_tables_count=f.get("data_tables_count", 0),
            columns=f.get("columns", []),
            sheets=f.get("sheets", 0),
        )
        for f in raw
    ]


@router.delete("/files/{file_id}")
async def delete_file(file_id: str):
    """Delete file from ALL systems: disk, Pinecone, DuckDB, catalog, notices, registry."""
    try:
        from src.file_router import delete_document
        result = delete_document(file_id)
        if "error" in result:
            return {"ok": False, "detail": result["error"]}
        return {"ok": True, "cleanup": result}
    except Exception as e:
        # Fallback to simple disk delete
        deleted = _file_service.delete(file_id)
        if not deleted:
            return {"ok": False, "detail": f"File not found: {e}"}
        return {"ok": True}


@router.post("/files/{file_id}/reindex")
async def reindex_file(file_id: str, background_tasks: BackgroundTasks):
    """Delete and re-index a single file (clean slate)."""
    from pathlib import Path
    from src.document_registry import get_document_registry
    from src.file_router import delete_document
    from src.document_rag import generate_doc_id

    registry = get_document_registry()
    rec = registry.get(file_id)
    if not rec:
        return {"ok": False, "detail": "Document not found"}

    file_path = rec.file_path
    file_name = rec.file_name

    # 1. Full cleanup from all stores
    delete_document(file_id)

    # 2. Check file still on disk (downloaded from GCS at startup)
    if not Path(file_path).exists():
        return {"ok": False, "detail": f"File not on disk: {file_path}"}

    # 3. Re-index in background
    new_doc_id = generate_doc_id(file_path)
    background_tasks.add_task(index_file_background, new_doc_id, file_path)

    return {"ok": True, "file_name": file_name, "new_file_id": new_doc_id, "status": "reindexing"}


@router.post("/files/reindex-stuck")
async def reindex_stuck_files(background_tasks: BackgroundTasks):
    """Find all processing/error files, clean them up, and re-index."""
    from pathlib import Path
    from src.document_registry import get_document_registry
    from src.file_router import delete_document
    from src.document_rag import generate_doc_id

    registry = get_document_registry()
    stuck = [r for r in registry.get_all() if r.status in ("processing", "error")]

    results = []
    for rec in stuck:
        file_path = rec.file_path
        # Full cleanup
        delete_document(rec.doc_id)

        # Check file on disk
        if not Path(file_path).exists():
            results.append({"name": rec.file_name, "status": "skipped", "reason": "file not on disk"})
            continue

        # Re-index
        new_id = generate_doc_id(file_path)
        background_tasks.add_task(index_file_background, new_id, file_path)
        results.append({"name": rec.file_name, "status": "reindexing", "new_id": new_id})

    return {"total": len(stuck), "results": results}


@router.get("/stats")
async def get_stats():
    """Return vector count and table count for dashboard metrics."""
    vectors = 0
    tables = 0
    try:
        from src.document_rag import get_document_rag
        rag = get_document_rag()
        vectors = len(rag.file_registry) if rag.file_registry else 0
        # Try getting actual vector count from index
        if hasattr(rag, 'index') and rag.index is not None:
            try:
                stats = rag.index._pinecone_index.describe_index_stats()
                vectors = stats.get("total_vector_count", vectors)
            except Exception:
                pass
    except Exception:
        pass
    try:
        from src.data_analyzer_sql import get_data_analyzer
        analyzer = get_data_analyzer()
        tables = len(analyzer.list_tables())
    except Exception:
        pass
    return {"vectors": vectors, "tables": tables}


@router.get("/files/export")
async def export_files_excel():
    """Export file list as multi-sheet Excel (.xlsx) grouped by file type."""
    import io
    from datetime import datetime
    try:
        import pandas as pd
        from openpyxl.styles import Font, Alignment
    except ImportError:
        from fastapi import HTTPException
        raise HTTPException(500, "pandas/openpyxl not available")

    raw = _file_service.list_files()

    # Group files by type
    groups = {
        "Documents": [f for f in raw if f.get("file_type") == "document"],
        "Emails": [f for f in raw if f.get("file_type") == "email"],
        "Data Files": [f for f in raw if f.get("file_type") == "data"],
    }

    def _fmt_date(iso_str):
        if not iso_str:
            return ""
        try:
            return datetime.fromisoformat(iso_str).strftime("%Y-%m-%d")
        except Exception:
            return iso_str[:10] if len(iso_str) >= 10 else iso_str

    # Column definitions per sheet type
    COLS = {
        "Documents": ["File Name", "Upload Date", "Document Date", "Pages", "Tables", "Rows"],
        "Emails": ["File Name", "Upload Date", "Document Date", "Sender", "Receiver", "Pages", "Tables", "Rows"],
        "Data Files": ["File Name", "Upload Date", "Document Date", "Sheets", "Tables", "Rows"],
    }

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for sheet_name, files in groups.items():
            rows = []
            for f in files:
                row = {
                    "File Name": f.get("name", ""),
                    "Upload Date": _fmt_date(f.get("created_at", "")),
                    "Document Date": f.get("document_date", ""),
                }
                if sheet_name == "Emails":
                    row["Sender"] = f.get("sender", "")
                    row["Receiver"] = f.get("recipient", "")
                    row["Pages"] = f.get("pages") or ""
                elif sheet_name == "Data Files":
                    row["Sheets"] = f.get("tables", 0)
                else:
                    row["Pages"] = f.get("pages") or ""
                row["Tables"] = f.get("tables", 0)
                row["Rows"] = f.get("rows", 0)
                rows.append(row)

            cols = COLS[sheet_name]
            df = pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)

            # Write data starting at row 3 (leave 2 rows for header)
            header_rows = 2
            df.to_excel(writer, index=False, sheet_name=sheet_name, startrow=header_rows)

            # Add notice/title header using openpyxl
            ws = writer.sheets[sheet_name]
            title_cell = ws.cell(row=1, column=1, value=f"COAir - {sheet_name}")
            title_cell.font = Font(bold=True, size=13)
            date_cell = ws.cell(row=2, column=1, value=f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
            date_cell.font = Font(italic=True, size=10, color="666666")

            # Auto-adjust column widths
            for col_idx, col_name in enumerate(cols, 1):
                max_len = len(col_name)
                for row_data in rows:
                    val = str(row_data.get(col_name, ""))
                    max_len = max(max_len, len(val))
                col_letter = ws.cell(row=1, column=col_idx).column_letter
                ws.column_dimensions[col_letter].width = min(max_len + 4, 50)

        # Add Summary sheet with document type breakdown
        summary_rows = []
        for sheet_name, files in groups.items():
            summary_rows.append({"Category": sheet_name, "Count": len(files)})
        # Add doc_type breakdown from notice metadata
        try:
            from src.document_registry import get_document_registry
            from src.notice_extractor import get_notice_extractor
            registry = get_document_registry()
            extractor = get_notice_extractor()
            doc_type_counts: dict[str, int] = {}
            for rec in registry.get_completed():
                if rec.notice_extracted:
                    notice = extractor.load_notice(rec.doc_id)
                    dt = (notice.doc_type if notice and notice.doc_type else "unclassified").title()
                else:
                    dt = rec.file_type.title() if rec.file_type else "Other"
                doc_type_counts[dt] = doc_type_counts.get(dt, 0) + 1
            summary_rows.append({"Category": "", "Count": ""})
            summary_rows.append({"Category": "Document Types", "Count": ""})
            for dt, count in sorted(doc_type_counts.items(), key=lambda x: x[1], reverse=True):
                summary_rows.append({"Category": f"  {dt}", "Count": count})
        except Exception:
            pass

        summary_df = pd.DataFrame(summary_rows) if summary_rows else pd.DataFrame(columns=["Category", "Count"])
        summary_df.to_excel(writer, index=False, sheet_name="Summary", startrow=2)
        ws_summary = writer.sheets["Summary"]
        ws_summary.cell(row=1, column=1, value="Project Document Summary").font = Font(bold=True, size=13)
        ws_summary.cell(row=2, column=1, value=f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}").font = Font(italic=True, size=10, color="666666")
        ws_summary.column_dimensions["A"].width = 30
        ws_summary.column_dimensions["B"].width = 12

    buf.seek(0)

    filename = "COAir_Documents.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
