"""Project management surface shown immediately after sign-in."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

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
    counts = {"document": 0, "email": 0, "data": 0, "programme": 0}
    status = {"queued": 0, "processing": 0, "ready": 0, "failed": 0}
    seen_names = set()
    for rec in files:
        seen_names.add(rec.file_name)
        counts[rec.file_type if rec.file_type in counts else "document"] += 1
        if rec.status == "completed":
            status["ready"] += 1
        elif rec.status == "error":
            status["failed"] += 1
        else:
            status["processing"] += 1

    # Bulk/legacy corpora were intentionally indexed without one registry row per
    # source file.  Once those records are assigned to a project, the chunk store
    # is the durable inventory for the project picker and readiness gate.
    try:
        from src.chunk_store import get_chunk_store
        rows = get_chunk_store().connection().execute(
            "SELECT file_name FROM chunks WHERE project_id=? "
            "AND file_name IS NOT NULL AND file_name<>'' GROUP BY file_name",
            [project_id],
        ).fetchall()
        for (file_name,) in rows:
            if file_name in seen_names:
                continue
            seen_names.add(file_name)
            ext = os.path.splitext(file_name)[1].lower()
            kind = ("email" if ext in (".eml", ".msg") else
                    "data" if ext in (".xlsx", ".xls", ".csv") else "document")
            counts[kind] += 1
            status["ready"] += 1
    except Exception:
        pass

    # Project-scoped spreadsheets live in the catalog rather than the text chunk
    # mirror, so include each source workbook once.
    try:
        from src.catalog import get_catalog
        for entry in get_catalog().entries.values():
            if (getattr(entry, "project_id", "") or "") != project_id:
                continue
            file_name = Path(entry.source_file).name
            if file_name in seen_names:
                continue
            seen_names.add(file_name)
            counts["data"] += 1
            status["ready"] += 1
    except Exception:
        pass
    try:
        from backend.tasks.ingestion_jobs import get_ingestion_job_store
        job_stats = get_ingestion_job_store().project_summary(project_id)
        # Jobs provide live queue/error state.  Ready inventory also includes
        # migrated vector-only sources which have no historical ingestion job.
        status["queued"] = max(status["queued"], job_stats.get("queued", 0))
        status["processing"] = max(status["processing"], job_stats.get("processing", 0))
        status["ready"] = max(status["ready"], job_stats.get("ready", 0))
        status["failed"] = max(status["failed"], job_stats.get("failed", 0))
    except Exception:
        job_stats = {}
    try:
        from src.forensic_store import get_forensic_store
        counts["programme"] = len(get_forensic_store().list_programmes(project_id))
    except Exception:
        pass
    try:
        vector_state = get_project_store().get_vector_state(project_id)
        vector = {
            "status": vector_state.get("status", "empty"),
            "point_count": int(vector_state.get("point_count") or 0),
            "embedding_profile": vector_state.get("embedding_profile", "local-bge-v1"),
            "last_error": vector_state.get("last_error"),
        }
    except Exception:
        vector = {
            "status": "error", "point_count": 0,
            "embedding_profile": "local-bge-v1",
            "last_error": "vector_state_unavailable",
        }
    return {
        "files": counts,
        "total_files": sum(counts.values()),
        **status,
        "eta_seconds": job_stats.get("eta_seconds") if job_stats else None,
        "calibration_size": job_stats.get("calibration_size", 0) if job_stats else 0,
        "calibration_complete": job_stats.get("calibration_complete", False) if job_stats else False,
        "report_ready": bool(seen_names) and status["processing"] == 0 and status["queued"] == 0
                        and status["ready"] > 0,
        "vector": vector,
    }


def _project_usage(project_id: str, user: UserContext) -> Dict:
    from src.billing_store import get_billing_store
    groups = get_billing_store().usage(
        project_id=project_id, username="" if user.role == "admin" else user.username,
    )["groups"]
    out = {
        "calls": sum(int(row.get("calls") or 0) for row in groups),
        "prompt_tokens": sum(int(row.get("prompt_tokens") or 0) for row in groups),
        "completion_tokens": sum(int(row.get("completion_tokens") or 0) for row in groups),
        "credits_used": round(sum(float(row.get("debited_credit") or 0) for row in groups), 6),
    }
    if user.role == "admin":
        out["retail_credits"] = round(sum(
            float(row.get("retail_credit") or 0) for row in groups
        ), 6)
        out["estimated_provider_cost_usd"] = round(sum(
            float(row.get("estimated_provider_cost_usd") or 0) for row in groups
        ), 9)
        out["uncovered_provider_cost_usd"] = round(sum(
            float(row.get("uncovered_provider_cost_usd") or 0) for row in groups
        ), 9)
        out["uncovered_credits"] = round(sum(
            float(row.get("uncovered_credit") or 0) for row in groups
        ), 6)
    return out


def _out(project: Dict, user: UserContext) -> Dict:
    return {**project, "stats": _stats(project["project_id"]),
            "usage": _project_usage(project["project_id"], user)}


@router.get("/projects")
def list_projects(
    user: UserContext = Depends(get_current_user),
    store: ProjectStore = Depends(get_project_store),
) -> Dict[str, Any]:
    projects = store.list_all() if user.role == "admin" else store.list_for_user(user.username)
    from src.user_store import get_user_store
    return {
        "projects": [_out(p, user) for p in projects],
        "account_usage": get_user_store().get_billing_summary(user.username),
    }


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
    return _out(project, user)


@router.patch("/projects/{project_id}")
def rename_project(
    project_id: str,
    body: ProjectRename,
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(require_project_owner),
    store: ProjectStore = Depends(get_project_store),
) -> Dict:
    if project.project_id != project_id:
        raise HTTPException(409, "selected_project_mismatch")
    updated = store.rename(project_id, body.name)
    if not updated:
        raise HTTPException(404, "project_not_found")
    updated["role"] = project.role
    return _out(updated, user)


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
