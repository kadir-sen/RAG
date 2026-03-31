"""Indexing status endpoints."""

from typing import List

from fastapi import APIRouter

from backend.models.responses import IndexingStatus
from backend.tasks.progress import indexing_progress

router = APIRouter()


@router.get("/indexing/status", response_model=List[IndexingStatus])
async def get_indexing_status():
    items = indexing_progress.all()
    return [
        IndexingStatus(
            file_id=s.file_id,
            filename=s.filename,
            status=s.status,
            progress=s.progress,
            error=s.error,
            details=s.details,
        )
        for s in items
    ]


@router.get("/files/{file_id}/status", response_model=IndexingStatus)
async def get_file_status(file_id: str):
    s = indexing_progress.get(file_id)
    if not s:
        return IndexingStatus(file_id=file_id, filename="", status="unknown")
    return IndexingStatus(
        file_id=s.file_id,
        filename=s.filename,
        status=s.status,
        progress=s.progress,
        error=s.error,
        details=s.details,
    )
