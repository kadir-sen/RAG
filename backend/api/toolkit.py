"""COAir boundary for the vendored Delay Analysis Toolkit."""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field

from backend.core.projects import ProjectContext, get_current_project, require_project_editor
from backend.core.security import UserContext, get_current_user, set_current_user_context
from backend.services.toolkit_service import ToolkitProgrammeService
from src.project_context import set_current_project
from src.project_store import get_project_store
from src.run_store import current_run_id_var
from src.toolkit_store import (
    MAX_ANALYSIS_BYTES, SESSION_TTL_SECONDS, TICKET_TTL_SECONDS,
    get_toolkit_store,
)


router = APIRouter(prefix="/toolkit")
internal_router = APIRouter(prefix="/internal/toolkit")
_service = ToolkitProgrammeService()
_lock_path = Path(__file__).resolve().parents[2] / "vendor" / "delay-analysis-toolkit.upstream.json"


def _upstream_sha() -> str:
    try:
        return str(json.loads(_lock_path.read_text(encoding="utf-8"))["commit"])
    except Exception:
        return os.getenv("TOOLKIT_UPSTREAM_SHA", "unknown")


def _require_service_secret(value: str | None) -> None:
    expected = os.getenv("TOOLKIT_SERVICE_SECRET", "")
    if not expected or not value:
        raise HTTPException(503 if not expected else 401, "toolkit_service_not_configured")
    import hmac
    if not hmac.compare_digest(value, expected):
        raise HTTPException(401, "invalid_toolkit_service_secret")


class TicketExchange(BaseModel):
    ticket: str = Field(min_length=20, max_length=256)


class NarrativeRequest(BaseModel):
    session_token: str = Field(min_length=20, max_length=256)
    prompt: str = Field(min_length=1, max_length=250_000)
    system: str = Field(default="", max_length=50_000)
    max_tokens: int = Field(default=4096, ge=128, le=8192)


@router.post("/programmes", status_code=201)
async def upload_programme(
    file: UploadFile = File(...),
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(require_project_editor),
):
    record, duplicate = await _service.save(
        file, project_id=project.project_id, username=user.username,
    )
    return {**record, "duplicate": duplicate}


@router.get("/programmes")
def list_programmes(project: ProjectContext = Depends(get_current_project)):
    return get_toolkit_store().list_programmes(project.project_id)


@router.delete("/programmes/{file_id}")
def delete_programme(
    file_id: str,
    project: ProjectContext = Depends(require_project_editor),
):
    if not _service.delete(project_id=project.project_id, file_id=file_id):
        raise HTTPException(404, "programme_not_found")
    return {"ok": True}


@router.post("/launch")
def launch_toolkit(
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(require_project_editor),
):
    programmes = get_toolkit_store().list_programmes(project.project_id)
    if not programmes:
        raise HTTPException(409, "programme_required")
    if sum(int(item["size_bytes"]) for item in programmes) > MAX_ANALYSIS_BYTES:
        raise HTTPException(413, "toolkit_analysis_size_exceeded")
    ticket = get_toolkit_store().create_ticket(
        username=user.username, project_id=project.project_id,
        project_role=project.role,
    )
    return {
        "launch_url": f"/toolkit/report-assembler?ticket={ticket}",
        "expires_in_seconds": TICKET_TTL_SECONDS,
        "upstream_sha": _upstream_sha(),
    }


@router.get("/status")
def toolkit_status():
    configured = bool(os.getenv("TOOLKIT_SERVICE_SECRET"))
    healthy = False
    if configured:
        try:
            import requests
            response = requests.get(
                os.getenv(
                    "TOOLKIT_HEALTH_URL",
                    "http://toolkit:8501/toolkit/_stcore/health",
                ),
                timeout=2,
            )
            healthy = response.ok
        except Exception:
            healthy = False
    return {
        "status": "ok" if healthy else ("unavailable" if configured else "unconfigured"),
        "coair_sha": os.getenv("COAIR_COMMIT_SHA", "development"),
        "upstream_sha": _upstream_sha(),
        "max_analysis_bytes": MAX_ANALYSIS_BYTES,
    }


@internal_router.post("/session")
def exchange_ticket(
    body: TicketExchange,
    x_toolkit_service: str | None = Header(default=None, alias="X-Toolkit-Service"),
):
    _require_service_secret(x_toolkit_service)
    session = get_toolkit_store().consume_ticket(body.ticket)
    if not session:
        raise HTTPException(401, "invalid_or_expired_toolkit_ticket")
    from src.user_store import get_user_store
    account = get_user_store().get_user(session["username"])
    if not account or not account.get("is_active"):
        raise HTTPException(401, "unknown_or_disabled_user")
    project = (get_project_store().get(session["project_id"])
               if account.get("role") == "admin" else
               get_project_store().get_for_user(session["project_id"], session["username"]))
    if not project or project.get("archived_at"):
        raise HTTPException(404, "project_not_found")
    current_role = "owner" if account.get("role") == "admin" else str(project.get("role") or "viewer")
    if current_role not in ("owner", "editor"):
        raise HTTPException(403, "project_editor_required")
    return {
        **session,
        "project_role": current_role,
        "project_name": project.get("name", ""),
        "programmes": get_toolkit_store().list_programmes(
            session["project_id"], include_path=True,
        ),
        "upstream_sha": _upstream_sha(),
        "session_ttl_seconds": SESSION_TTL_SECONDS,
    }


@internal_router.post("/narrative")
def generate_toolkit_narrative(
    body: NarrativeRequest,
    x_toolkit_service: str | None = Header(default=None, alias="X-Toolkit-Service"),
):
    _require_service_secret(x_toolkit_service)
    session = get_toolkit_store().validate_session(body.session_token)
    if not session:
        raise HTTPException(401, "invalid_or_expired_toolkit_session")
    user = set_current_user_context(session["username"])
    if not user:
        raise HTTPException(401, "unknown_or_disabled_user")
    project = (get_project_store().get(session["project_id"])
               if user.role == "admin" else
               get_project_store().get_for_user(session["project_id"], user.username))
    if not project or project.get("archived_at"):
        raise HTTPException(404, "project_not_found")
    current_role = "owner" if user.role == "admin" else str(project.get("role") or "viewer")
    if current_role not in ("owner", "editor"):
        raise HTTPException(403, "project_editor_required")
    set_current_project(session["project_id"], current_role)
    current_run_id_var.set(f"toolkit-{str(session['ticket_hash'])[:16]}")
    from src.llm_client import generate_text
    response = generate_text(
        body.prompt,
        system=body.system,
        provider="gemini",
        model="gemini-3.6-flash",
        max_tokens=body.max_tokens,
        thinking_level="medium",
        task_type="toolkit_report",
    )
    return {
        "text": response.text,
        "model": response.usage.model,
        "prompt_tokens": response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
    }
