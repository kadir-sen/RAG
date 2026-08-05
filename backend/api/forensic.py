"""Native COAir forensic programme analysis API."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Dict, List, Literal, Optional, Union

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.core.projects import ProjectContext, get_current_project, require_project_editor
from backend.core.security import UserContext, get_current_user
from backend.services.forensic_toolkit import MODULE_DEFINITIONS, ForensicProgrammeService
from src.forensic_store import MAX_WORKSPACE_BYTES, UPSTREAM_SHA, get_forensic_store


router = APIRouter()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ProgrammeFile(StrictModel):
    file_id: str
    name: str
    size_bytes: int
    sha256: str
    created_at: str


class WorkspaceCreate(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    programme_ids: List[str] = Field(min_length=1, max_length=30)
    settings: Dict[str, Union[str, int, float, bool]] = Field(default_factory=dict)


class WorkspaceUpdate(StrictModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    programme_ids: Optional[List[str]] = Field(default=None, min_length=1, max_length=30)
    settings: Optional[Dict[str, Union[str, int, float, bool]]] = None


class IndexParameters(StrictModel):
    programme_index: int = -1


class IntakeParameters(StrictModel):
    kind: Literal["intake"]


class DcmaParameters(IndexParameters):
    kind: Literal["dcma"]
    thresholds: Dict[str, Union[int, float, bool]] = Field(default_factory=dict)


class CriticalPathParameters(IndexParameters):
    kind: Literal["baseline-critical-path"]
    programme_index: int = 0
    method: Literal["longest_path", "float"] = "longest_path"
    float_tolerance_days: float = Field(default=0, ge=-3650, le=3650)
    near_critical_days: float = Field(default=10, ge=0, le=3650)
    branch_tolerance_hours: float = Field(default=1, ge=0, le=168)
    end_task_code: str = Field(default="", max_length=120)


class ComparisonParameters(StrictModel):
    kind: Literal["revision-comparison"]
    old_index: int = 0
    new_index: int = -1
    end_task_code: str = Field(default="", max_length=120)


class OosParameters(IndexParameters):
    kind: Literal["out-of-sequence"]


class FloatParameters(StrictModel):
    kind: Literal["float-erosion"]
    near_critical_days: float = Field(default=10, ge=0, le=3650)


class ProgressParameters(StrictModel):
    kind: Literal["progress-s-curve"]
    weight_scheme: Literal["duration", "count", "resource_qty"] = "duration"


class ResourcesParameters(IndexParameters):
    kind: Literal["resource-loading"]
    programme_index: int = 0


class SequenceParameters(IndexParameters):
    kind: Literal["sequence-coding"]
    mapping_confirmed: bool = False
    min_front_activities: int = Field(default=3, ge=1, le=1000)


class HierarchyParameters(IndexParameters):
    kind: Literal["hierarchy"]
    dimension_ids: List[str] = Field(default_factory=list, max_length=8)


class MilestoneParameters(StrictModel):
    kind: Literal["milestone-shift"]


class TransferParameters(StrictModel):
    kind: Literal["progress-transfer"]
    network_index: int = 0
    progress_index: int = -1


class AsBuiltParameters(StrictModel):
    kind: Literal["as-built-critical-path"]
    end_task_code: str = Field(default="", max_length=120)
    max_gap_days: float = Field(default=15, ge=0, le=3650)
    allow_temporal_fallback: bool = True
    allow_forecast_tail: bool = True


class ReportAssemblerParameters(StrictModel):
    kind: Literal["report-assembler"]
    report_title: str = Field(default="Forensic Programme Analysis", min_length=3, max_length=240)


class ApabParameters(StrictModel):
    kind: Literal["as-planned-vs-as-built"]
    activity_codes: List[str] = Field(default_factory=list, max_length=5000)
    date_basis: Literal["target", "late", "early"] = "target"


class WindowsParameters(StrictModel):
    kind: Literal["windows-analysis"]
    end_task_code: str = Field(default="", max_length=120)
    switch_threshold: float = Field(default=.5, ge=0, le=1)
    bifurcate: bool = True


class FragnetLink(StrictModel):
    link_id: str = Field(alias="id", min_length=1, max_length=120)
    type: Literal["FS", "SS", "FF", "SF"] = "FS"
    lag_days: float = Field(default=0, ge=-3650, le=3650)


class FragnetActivity(StrictModel):
    activity_id: str = Field(alias="id", min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=500)
    duration_days: float = Field(ge=0, le=3650)
    predecessors: List[FragnetLink] = Field(default_factory=list, max_length=100)
    successors: List[FragnetLink] = Field(default_factory=list, max_length=100)
    rationale: str = Field(default="", max_length=2000)
    assumptions: str = Field(default="", max_length=2000)
    confidence: Literal["low", "medium", "high"] = "medium"
    calendar_id: str = Field(default="", max_length=120)


class DelayEvent(StrictModel):
    event_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=5000)
    date_raised: str = Field(default="", max_length=10)
    responsibility_asserted: str = Field(default="", max_length=300)
    evidence_note: str = Field(default="", max_length=3000)
    area: str = Field(default="", max_length=300)
    discipline: str = Field(default="", max_length=300)
    project_context: str = Field(default="", max_length=3000)
    work_package: str = Field(default="", max_length=300)


class EventRecord(StrictModel):
    event: DelayEvent
    fragnet: List[FragnetActivity] = Field(min_length=1, max_length=100)


class IapParameters(StrictModel):
    kind: Literal["impacted-as-planned"]
    events: List[EventRecord] = Field(min_length=1, max_length=100)


class CabParameters(IndexParameters):
    kind: Literal["collapsed-as-built"]
    remove_activity_codes: List[str] = Field(min_length=1, max_length=5000)
    anchor_code: str = Field(default="", max_length=120)


class TiaParameters(IndexParameters):
    kind: Literal["time-impact-analysis"]
    events: List[EventRecord] = Field(min_length=1, max_length=1)
    target_milestone: str = Field(default="", max_length=120)


RunParameters = Annotated[Union[
    IntakeParameters, DcmaParameters, CriticalPathParameters, ComparisonParameters,
    OosParameters, FloatParameters, ProgressParameters, ResourcesParameters,
    SequenceParameters, HierarchyParameters, MilestoneParameters, TransferParameters,
    AsBuiltParameters, ReportAssemblerParameters, ApabParameters, WindowsParameters,
    IapParameters, CabParameters, TiaParameters,
], Field(discriminator="kind")]


class RunCreate(StrictModel):
    parameters: RunParameters
    ai_narrative: bool = False


def _enabled(user: UserContext) -> None:
    enabled = os.getenv("FORENSIC_NATIVE_UI_V1", "false").casefold() in {"1", "true", "yes", "on"}
    if not enabled and user.role != "admin":
        raise HTTPException(404, "forensic_native_ui_disabled")


def _workspace_public(workspace: dict) -> dict:
    return {key: workspace[key] for key in (
        "workspace_id", "project_id", "name", "programme_ids", "settings",
        "source_revision", "upstream_sha", "created_at", "updated_at",
    )}


def _run_public(run: dict, user: UserContext, project_id: str) -> dict:
    value = {key: run.get(key) for key in (
        "run_id", "workspace_id", "project_id", "module_slug", "status", "stage",
        "progress", "parameters", "result", "error_code", "attempt", "created_at",
        "started_at", "completed_at", "updated_at", "upstream_sha", "source_revision",
    )}
    value["artifacts"] = get_forensic_store().list_artifacts(project_id, run["run_id"])
    if user.role == "admin":
        value["source_hashes"] = run.get("source_hashes")
        value["traceback_id"] = run.get("traceback_id")
    return value


@router.get("/forensic/status")
def forensic_status(user: UserContext = Depends(get_current_user)):
    enabled = os.getenv("FORENSIC_NATIVE_UI_V1", "false").casefold() in {"1", "true", "yes", "on"}
    return {"available": enabled or user.role == "admin", "enabled": enabled,
            "coair_sha": os.getenv("COAIR_COMMIT_SHA", "development"),
            "upstream_sha": UPSTREAM_SHA, "streamlit": False,
            "max_workspace_bytes": MAX_WORKSPACE_BYTES,
            "modules": [{"slug": slug, **definition}
                        for slug, definition in MODULE_DEFINITIONS.items()]}


@router.get("/forensic/programmes")
def list_programmes(
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(get_current_project),
):
    _enabled(user)
    return {"programmes": get_forensic_store().list_programmes(project.project_id),
            "max_workspace_bytes": MAX_WORKSPACE_BYTES}


@router.post("/forensic/programmes", status_code=201)
async def upload_programme(
    file: UploadFile = File(...),
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(require_project_editor),
):
    _enabled(user)
    record, duplicate = await ForensicProgrammeService().save(
        file, project_id=project.project_id, username=user.username,
    )
    return {**record, "duplicate": duplicate}


@router.delete("/forensic/programmes/{file_id}", status_code=204)
def delete_programme(
    file_id: str, user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(require_project_editor),
):
    _enabled(user)
    if not ForensicProgrammeService().delete(project_id=project.project_id, file_id=file_id):
        raise HTTPException(404, "forensic_programme_not_found")


@router.get("/forensic/workspaces")
def list_workspaces(
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(get_current_project),
):
    _enabled(user)
    return {"workspaces": [_workspace_public(item) for item in
                           get_forensic_store().list_workspaces(project.project_id)]}


@router.post("/forensic/workspaces", status_code=201)
def create_workspace(
    body: WorkspaceCreate, user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(require_project_editor),
):
    _enabled(user)
    try:
        value = get_forensic_store().create_workspace(
            project_id=project.project_id, username=user.username, name=body.name.strip(),
            programme_ids=body.programme_ids, settings=body.settings,
        )
    except ValueError as exc:
        raise HTTPException(413 if "size_exceeded" in str(exc) else 422, str(exc)) from exc
    return _workspace_public(value)


@router.get("/forensic/workspaces/{workspace_id}")
def get_workspace(
    workspace_id: str, user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(get_current_project),
):
    _enabled(user)
    value = get_forensic_store().get_workspace(project.project_id, workspace_id)
    if not value:
        raise HTTPException(404, "forensic_workspace_not_found")
    return _workspace_public(value)


@router.patch("/forensic/workspaces/{workspace_id}")
def update_workspace(
    workspace_id: str, body: WorkspaceUpdate,
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(require_project_editor),
):
    _enabled(user)
    try:
        value = get_forensic_store().update_workspace(
            project_id=project.project_id, workspace_id=workspace_id,
            name=body.name.strip() if body.name else None,
            programme_ids=body.programme_ids, settings=body.settings,
        )
    except ValueError as exc:
        raise HTTPException(413 if "size_exceeded" in str(exc) else 422, str(exc)) from exc
    if not value:
        raise HTTPException(404, "forensic_workspace_not_found")
    return _workspace_public(value)


@router.get("/forensic/runs")
def list_runs(
    workspace_id: str = "", user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(get_current_project),
):
    _enabled(user)
    return {"runs": [_run_public(run, user, project.project_id) for run in
                     get_forensic_store().list_runs(project.project_id, workspace_id)]}


@router.post("/forensic/workspaces/{workspace_id}/modules/{module_slug}/runs", status_code=202)
def create_run(
    workspace_id: str, module_slug: str, body: RunCreate,
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(require_project_editor),
):
    _enabled(user)
    if module_slug not in MODULE_DEFINITIONS:
        raise HTTPException(404, "forensic_module_not_found")
    parameters = body.parameters.model_dump(by_alias=True)
    if parameters.pop("kind") != module_slug:
        raise HTTPException(422, "forensic_module_parameter_mismatch")
    parameters["_ai_narrative"] = body.ai_narrative
    try:
        run = get_forensic_store().enqueue_run(
            project_id=project.project_id, workspace_id=workspace_id,
            username=user.username, module_slug=module_slug, parameters=parameters,
        )
    except ValueError as exc:
        raise HTTPException(409 if "changed" in str(exc) else 404, str(exc)) from exc
    return _run_public(run, user, project.project_id)


@router.get("/forensic/runs/{run_id}")
def get_run(
    run_id: str, user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(get_current_project),
):
    _enabled(user)
    run = get_forensic_store().get_run(project.project_id, run_id)
    if not run:
        raise HTTPException(404, "forensic_run_not_found")
    return _run_public(run, user, project.project_id)


@router.post("/forensic/runs/{run_id}/retry", status_code=202)
def retry_run(
    run_id: str, user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(require_project_editor),
):
    _enabled(user)
    run = get_forensic_store().retry_run(project.project_id, run_id)
    if not run:
        raise HTTPException(409, "forensic_run_not_retryable")
    return _run_public(run, user, project.project_id)


@router.get("/forensic/artifacts/{artifact_id}/download")
def download_artifact(
    artifact_id: str, user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(get_current_project),
):
    _enabled(user)
    artifact = get_forensic_store().get_artifact(
        project.project_id, artifact_id, include_path=True,
    )
    if not artifact or not Path(artifact["file_path"]).is_file():
        raise HTTPException(404, "forensic_artifact_not_found")
    return FileResponse(artifact["file_path"], media_type=artifact["mime_type"],
                        filename=artifact["name"])


__all__ = ["router"]
