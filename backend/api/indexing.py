"""Indexing status endpoints."""

from typing import List

from fastapi import APIRouter, Depends

from backend.models.responses import IndexingStatus
from backend.tasks.progress import indexing_progress
from backend.core.projects import ProjectContext, get_current_project
from backend.tasks.ingestion_jobs import get_ingestion_job_store

router = APIRouter()


@router.get("/indexing/status", response_model=List[IndexingStatus])
async def get_indexing_status(project: ProjectContext = Depends(get_current_project)):
    items = get_ingestion_job_store().list_project(project.project_id)
    return [
        IndexingStatus(
            file_id=s["file_id"],
            filename=s["filename"],
            status=s["stage"] if s["status"] == "processing" else s["status"],
            progress=s["progress"],
            error=s["error"],
            details={**s["details"], "job_id": s["job_id"], "stage": s["stage"]},
        )
        for s in items
    ]


@router.get("/indexing/summary")
async def get_indexing_summary(project: ProjectContext = Depends(get_current_project)):
    return get_ingestion_job_store().project_summary(project.project_id)


@router.get("/files/{file_id}/status", response_model=IndexingStatus)
async def get_file_status(
    file_id: str,
    project: ProjectContext = Depends(get_current_project),
):
    s = get_ingestion_job_store().get_by_file(file_id, project.project_id)
    if not s:
        return IndexingStatus(file_id=file_id, filename="", status="unknown")
    return IndexingStatus(
        file_id=s["file_id"],
        filename=s["filename"],
        status=s["stage"] if s["status"] == "processing" else s["status"],
        progress=s["progress"],
        error=s["error"],
        details={**s["details"], "job_id": s["job_id"], "stage": s["stage"]},
    )
