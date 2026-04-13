"""File upload, listing, deletion, stats, and export endpoints."""

from typing import List

from fastapi import APIRouter, UploadFile, File, BackgroundTasks
from fastapi.responses import StreamingResponse

from backend.models.responses import FileInfo, UploadResult
from backend.services.file_service import FileService
from backend.tasks.indexing import index_file_background

router = APIRouter()
_file_service = FileService()


@router.post("/upload", response_model=UploadResult)
async def upload_file(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    saved_path, file_id, is_duplicate = await _file_service.save(file)
    if is_duplicate:
        return UploadResult(
            file_id=file_id,
            filename=file.filename,
            status="completed",
        )
    background_tasks.add_task(index_file_background, file_id, saved_path)
    return UploadResult(
        file_id=file_id,
        filename=file.filename,
        status="indexing",
    )


@router.get("/files", response_model=List[FileInfo])
async def list_files():
    raw = _file_service.list_files()
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
            title_cell = ws.cell(row=1, column=1, value=f"AI Construction Project Intelligence - {sheet_name}")
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

    buf.seek(0)

    filename = "AI_Construction_Project_Intelligence_Documents.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
