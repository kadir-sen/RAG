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
    """Export file list as Excel (.xlsx) download."""
    import io
    from datetime import datetime
    try:
        import pandas as pd
    except ImportError:
        from fastapi import HTTPException
        raise HTTPException(500, "pandas not available")

    raw = _file_service.list_files()
    rows = []
    for f in raw:
        rows.append({
            "File Name": f.get("name", ""),
            "Type": f.get("file_type", ""),
            "Pages": f.get("pages") or "",
            "OCR Pages": f.get("ocr_pages", 0),
            "Tables": f.get("tables", 0),
            "Rows": f.get("rows", 0),
        })

    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["File Name", "Type", "Pages", "OCR Pages", "Tables", "Rows"]
    )
    buf = io.BytesIO()
    df.to_excel(buf, index=False, sheet_name="Uploaded Files")
    buf.seek(0)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="uploaded_files_{ts}.xlsx"'},
    )
