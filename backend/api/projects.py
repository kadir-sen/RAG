"""Project management surface shown immediately after sign-in."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.projects import ProjectContext, require_project_owner, server_embedding_profile
from backend.core.security import UserContext, get_current_user
from src.config import BASE_DIR, STORAGE_DIR
from src.project_store import ProjectStore, get_project_store


router = APIRouter()


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    embedding_profile: str = "local-bge-v1"


class ProjectRename(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class ProjectMemberRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    role: str


def _ensure_dirs(project_id: str) -> None:
    for root in (Path(BASE_DIR) / "data" / "projects", Path(STORAGE_DIR) / "projects"):
        for child in ("documents", "emails", "tables", "reports", "jobs"):
            (root / project_id / child).mkdir(parents=True, exist_ok=True)


def _stats(project_id: str) -> Dict:
    files = []
    try:
        from src.document_registry import get_document_registry
        files = get_document_registry().get_all(project_id=project_id)
    except Exception:
        pass
    counts = {"document": 0, "email": 0, "data": 0}
    status = {"queued": 0, "processing": 0, "ready": 0, "failed": 0}
    for rec in files:
        counts[rec.file_type if rec.file_type in counts else "document"] += 1
        if rec.status == "completed":
            status["ready"] += 1
        elif rec.status == "error":
            status["failed"] += 1
        else:
            status["processing"] += 1
    try:
        from backend.tasks.ingestion_jobs import get_ingestion_job_store
        job_stats = get_ingestion_job_store().project_summary(project_id)
        status.update(job_stats)
    except Exception:
        job_stats = {}
    return {
        "files": counts,
        "total_files": sum(counts.values()),
        **status,
        "eta_seconds": job_stats.get("eta_seconds") if job_stats else None,
        "calibration_size": job_stats.get("calibration_size", 0) if job_stats else 0,
        "calibration_complete": job_stats.get("calibration_complete", False) if job_stats else False,
        "report_ready": bool(files) and status["processing"] == 0 and status["queued"] == 0
                        and status["ready"] > 0,
    }


def _out(project: Dict) -> Dict:
    return {**project, "stats": _stats(project["project_id"])}


@router.get("/projects")
def list_projects(
    user: UserContext = Depends(get_current_user),
    store: ProjectStore = Depends(get_project_store),
) -> Dict[str, List[Dict]]:
    projects = store.list_all() if user.role == "admin" else store.list_for_user(user.username)
    return {"projects": [_out(p) for p in projects]}


@router.post("/projects", status_code=201)
def create_project(
    body: ProjectCreate,
    user: UserContext = Depends(get_current_user),
    store: ProjectStore = Depends(get_project_store),
) -> Dict:
    if body.embedding_profile != server_embedding_profile():
        raise HTTPException(422, {
            "error": "embedding_profile_unavailable",
            "server_profile": server_embedding_profile(),
        })
    try:
        project = store.create_project(
            body.name,
            user.username,
            embedding_profile=body.embedding_profile,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _ensure_dirs(project["project_id"])
    return _out(project)


@router.patch("/projects/{project_id}")
def rename_project(
    project_id: str,
    body: ProjectRename,
    project: ProjectContext = Depends(require_project_owner),
    store: ProjectStore = Depends(get_project_store),
) -> Dict:
    if project.project_id != project_id:
        raise HTTPException(409, "selected_project_mismatch")
    updated = store.rename(project_id, body.name)
    if not updated:
        raise HTTPException(404, "project_not_found")
    updated["role"] = project.role
    return _out(updated)


@router.post("/projects/{project_id}/members")
def add_project_member(
    project_id: str,
    body: ProjectMemberRequest,
    project: ProjectContext = Depends(require_project_owner),
    store: ProjectStore = Depends(get_project_store),
) -> Dict:
    if project.project_id != project_id:
        raise HTTPException(409, "selected_project_mismatch")
    from src.user_store import get_user_store
    if not get_user_store().get_user(body.username):
        raise HTTPException(404, "user_not_found")
    try:
        store.add_member(project_id, body.username, body.role)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True}


@router.delete("/projects/{project_id}")
def archive_project(
    project_id: str,
    project: ProjectContext = Depends(require_project_owner),
    store: ProjectStore = Depends(get_project_store),
) -> Dict:
    if project.project_id != project_id:
        raise HTTPException(409, "selected_project_mismatch")
    return {"ok": store.archive(project_id)}
