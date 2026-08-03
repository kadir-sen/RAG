"""Indexing status endpoints."""

from typing import List

from fastapi import APIRouter, Depends

from backend.models.responses import IndexingStatus
from backend.tasks.progress import indexing_progress
from backend.core.projects import ProjectContext, get_current_project, require_project_editor
from backend.core.security import UserContext, get_current_user
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


@router.post("/files/{file_id}/retry", response_model=IndexingStatus)
async def retry_file_indexing(
    file_id: str,
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(require_project_editor),
):
    """Requeue an existing source without uploading or charging storage again."""
    from fastapi import HTTPException
    from src.document_registry import get_document_registry
    from src.user_store import get_user_store

    record = get_document_registry().get(file_id)
    if not record or (getattr(record, "project_id", "") or "") != project.project_id:
        raise HTTPException(404, "file_not_found")
    user_store = get_user_store()
    account = user_store.billing.get_account(user.username)
    if account and account.get("plan_type") == "demo":
        user_store.billing.enforce_credits(user.username)
    job = get_ingestion_job_store().enqueue(
        project.project_id, file_id, record.file_path, record.file_name,
        requested_by=user.username,
    )
    return IndexingStatus(
        file_id=job["file_id"], filename=job["filename"], status=job["status"],
        progress=job["progress"], error=job["error"],
        details={**job["details"], "job_id": job["job_id"], "stage": job["stage"]},
    )
