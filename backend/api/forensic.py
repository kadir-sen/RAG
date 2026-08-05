"""Native COAir forensic programme analysis API."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.core.projects import ProjectContext, get_current_project, require_project_editor
from backend.core.security import UserContext, get_current_user
from backend.services.forensic_toolkit import (
    MODULE_DEFINITIONS, ForensicActionError, ForensicActionService,
    ForensicProgrammeService, ForensicSourceService,
)
from backend.services.forensic_toolkit.parity import (
    MODULE_PARITY, PARITY_VERSION, parity_fingerprint,
)
from src.forensic_store import MAX_WORKSPACE_BYTES, UPSTREAM_SHA, get_forensic_store
from src.billing_store import CreditBalanceExceededError


router = APIRouter()


def _flag(name: str) -> bool:
    return os.getenv(name, "false").casefold() in {"1", "true", "yes", "on"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ProgrammeFile(StrictModel):
    file_id: str
    name: str
    size_bytes: int
    sha256: str
    created_at: str


class SourceScope(StrictModel):
    pages: List[int] = Field(default_factory=list, max_length=1000)
    sheet: str = Field(default="", max_length=240)
    row_from: Optional[int] = Field(default=None, ge=1)
    row_to: Optional[int] = Field(default=None, ge=1)


class SourceSelectionItem(StrictModel):
    source_id: str = Field(min_length=1, max_length=500)
    selected_scope: SourceScope = Field(default_factory=SourceScope)


class SourceSelectionUpdate(StrictModel):
    expected_version: int = Field(ge=1)
    sources: List[SourceSelectionItem] = Field(min_length=1, max_length=500)


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
    repair_activity_pairs: List[str] = Field(default_factory=list, max_length=5000)
    build_repaired_xer: bool = False


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


class ApabStatePatch(StrictModel):
    milestones: Optional[List[str]] = Field(default=None, max_length=100)
    paths: Optional[Dict[str, List[str]]] = None
    path_basis: Optional[Dict[str, str]] = None
    key_dates: Optional[Dict[str, str]] = None
    date_basis: Optional[Literal["target", "late", "early"]] = None


class UmbrellaGroup(StrictModel):
    name: str = Field(min_length=1, max_length=240)
    activity_codes: List[str] = Field(default_factory=list, max_length=10000)


class UmbrellaRound(StrictModel):
    round_number: int = Field(ge=1, le=3)
    instruction: str = Field(default="", max_length=5000)
    status: Literal["proposed", "accepted", "rejected"] = "proposed"


class UmbrellaStatePatch(StrictModel):
    groups: Optional[List[UmbrellaGroup]] = None
    proposed: Optional[List[UmbrellaGroup]] = None
    rounds: Optional[List[UmbrellaRound]] = None


class SequenceMappingRow(StrictModel):
    task_code: str = Field(min_length=1, max_length=120)
    name: str = Field(default="", max_length=500)
    front: str = Field(default="", max_length=240)
    stage: str = Field(default="", max_length=240)
    rationale: str = Field(default="", max_length=1000)


class SequenceStatePatch(StrictModel):
    programme_id: str = Field(default="", max_length=500)
    rows: Optional[List[SequenceMappingRow]] = None
    confirmed: Optional[bool] = None


class ConfirmedDriver(StrictModel):
    milestone: str = Field(min_length=1, max_length=120)
    window: str = Field(min_length=1, max_length=240)
    task_code: str = Field(min_length=1, max_length=120)
    direction: str = Field(default="", max_length=120)
    evidence_note: str = Field(min_length=1, max_length=3000)


class NarrativeRecord(StrictModel):
    text: str = Field(min_length=1, max_length=200000)
    template: str = Field(default="", max_length=20000)
    run_id: str = Field(default="", max_length=120)
    model: Literal["gemini-3.6-flash"] = "gemini-3.6-flash"


class ReportStatePatch(StrictModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=240)
    project: Optional[str] = Field(default=None, max_length=240)
    prepared_by: Optional[str] = Field(default=None, max_length=240)
    selected_sections: Optional[List[str]] = Field(default=None, max_length=100)
    include_charts: Optional[bool] = None


class WorkspaceStatePatch(StrictModel):
    expected_version: int = Field(ge=1)
    baseline_programme_id: Optional[str] = Field(default=None, max_length=500)
    current_programme_id: Optional[str] = Field(default=None, max_length=500)
    contract_completion_milestone: Optional[str] = Field(default=None, max_length=120)
    missing_inputs: Optional[List[str]] = Field(default=None, max_length=200)
    analysis_basis: Optional[Dict[str, List[str]]] = None
    event_register: Optional[Dict[str, EventRecord]] = None
    apab: Optional[ApabStatePatch] = None
    umbrella: Optional[UmbrellaStatePatch] = None
    sequence: Optional[SequenceStatePatch] = None
    hierarchy_configurations: Optional[Dict[str, List[str]]] = None
    explain_confirmed_drivers: Optional[List[ConfirmedDriver]] = None
    iap_events: Optional[List[EventRecord]] = None
    cab_groups: Optional[List[UmbrellaGroup]] = None
    cab_extracted_activity_codes: Optional[List[str]] = Field(default=None, max_length=10000)
    narratives: Optional[Dict[str, NarrativeRecord]] = None
    report: Optional[ReportStatePatch] = None


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


class RunModuleAction(StrictModel):
    action: Literal["run"] = "run"
    expected_version: int = Field(ge=1)
    parameters: RunParameters
    ai_narrative: bool = False


class ExtractEventsAction(StrictModel):
    action: Literal["extract_events"]
    expected_version: int = Field(ge=1)
    source_ids: List[str] = Field(min_length=1, max_length=20)
    query: str = Field(default="", max_length=2000)


class GenerateNarrativeAction(StrictModel):
    action: Literal["generate_narrative"]
    expected_version: int = Field(ge=1)
    run_id: str = Field(min_length=1, max_length=120)
    analyst_instructions: str = Field(default="", max_length=5000)


class ExtractClauseAction(StrictModel):
    action: Literal["extract_clause"]
    expected_version: int = Field(ge=1)
    source_ids: List[str] = Field(min_length=1, max_length=10)


class RecommendFragnetAction(StrictModel):
    action: Literal["recommend_fragnet"]
    expected_version: int = Field(ge=1)
    programme_id: str = Field(min_length=1, max_length=500)
    event: DelayEvent


class RecommendLogicAction(StrictModel):
    action: Literal["recommend_logic"]
    expected_version: int = Field(ge=1)
    programme_id: str = Field(min_length=1, max_length=500)
    event: DelayEvent
    fragnet: List[FragnetActivity] = Field(min_length=1, max_length=100)


class ReviewSequenceAction(StrictModel):
    action: Literal["ai_review"]
    expected_version: int = Field(ge=1)
    programme_id: str = Field(min_length=1, max_length=500)
    rows: List[SequenceMappingRow] = Field(min_length=1, max_length=5000)


ModuleActionRequest = Annotated[
    Union[RunModuleAction, ExtractEventsAction, GenerateNarrativeAction,
          ExtractClauseAction, RecommendFragnetAction, RecommendLogicAction,
          ReviewSequenceAction],
    Field(discriminator="action"),
]


def _enabled(user: UserContext) -> None:
    enabled = any(os.getenv(name, "false").casefold() in {"1", "true", "yes", "on"}
                  for name in ("FORENSIC_NATIVE_UI_V1", "FORENSIC_PARITY_UI_V1"))
    if not enabled and user.role != "admin":
        raise HTTPException(404, "forensic_native_ui_disabled")


def _parity_enabled(user: UserContext) -> None:
    # The parity workspace is intentionally an administrator validation surface
    # until the separate public cutover flag is enabled.  This prevents a
    # staging flag from exposing an incomplete analyst workflow to end users.
    if user.role != "admin" and not _flag("FORENSIC_PARITY_PUBLIC_V1"):
        raise HTTPException(404, "forensic_parity_ui_disabled")


def _workspace_public(workspace: dict) -> dict:
    value = {key: workspace[key] for key in (
        "workspace_id", "project_id", "name", "programme_ids", "settings",
        "source_revision", "upstream_sha", "created_at", "updated_at",
    )}
    state = get_forensic_store().get_workspace_state(
        workspace["project_id"], workspace["workspace_id"],
    )
    sources = get_forensic_store().list_workspace_sources(
        workspace["project_id"], workspace["workspace_id"],
    )
    value["state_version"] = int((state or {}).get("version") or 1)
    value["pipeline_version"] = str(
        ((state or {}).get("state") or {}).get("pipeline_version") or "legacy-native-v1"
    )
    value["evidence_source_ids"] = [item["source_id"] for item in sources
                                    if item["source_kind"] != "programme"]
    return value


def _workspace_state_patch(body: WorkspaceStatePatch) -> Dict[str, Any]:
    raw = body.model_dump(exclude={"expected_version"}, exclude_none=True)
    patch: Dict[str, Any] = {}
    for key in ("baseline_programme_id", "current_programme_id",
                "contract_completion_milestone", "missing_inputs", "analysis_basis"):
        if key in raw:
            patch[key] = raw[key]
    if "event_register" in raw:
        patch["event_register"] = raw["event_register"]
    if "apab" in raw:
        patch["apab"] = raw["apab"]
    if "umbrella" in raw:
        umbrella = raw["umbrella"]
        if "groups" in umbrella:
            umbrella["groups"] = {item["name"]: item["activity_codes"]
                                  for item in umbrella["groups"]}
        patch["umbrella"] = umbrella
    if "sequence" in raw:
        sequence = raw["sequence"]
        programme_id = sequence.pop("programme_id", "")
        state: Dict[str, Any] = {}
        if "rows" in sequence:
            state["mappings"] = {programme_id: sequence["rows"]}
        if "confirmed" in sequence:
            state["confirmed"] = {programme_id: sequence["confirmed"]}
        patch["sequence"] = state
    if "hierarchy_configurations" in raw:
        patch["hierarchy"] = {"saved_configurations": raw["hierarchy_configurations"]}
    if "explain_confirmed_drivers" in raw:
        patch["explain"] = {"confirmed_drivers": raw["explain_confirmed_drivers"]}
    if "iap_events" in raw:
        patch["iap"] = {"events": raw["iap_events"]}
    if "cab_groups" in raw or "cab_extracted_activity_codes" in raw:
        cab: Dict[str, Any] = {}
        if "cab_groups" in raw:
            cab["groups"] = raw["cab_groups"]
        if "cab_extracted_activity_codes" in raw:
            cab["extracted_activity_codes"] = raw["cab_extracted_activity_codes"]
        patch["cab"] = cab
    if "narratives" in raw:
        patch["narratives"] = raw["narratives"]
    if "report" in raw:
        patch["report"] = raw["report"]
    return patch


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
    enabled = _flag("FORENSIC_NATIVE_UI_V1")
    parity_validation = _flag("FORENSIC_PARITY_UI_V1")
    parity_public = _flag("FORENSIC_PARITY_PUBLIC_V1")
    parity_available = user.role == "admin" or parity_public
    return {"available": enabled or parity_available,
            "enabled": enabled or parity_public,
            "parity_available": parity_available,
            "parity_enabled": parity_public,
            "parity_validation": parity_validation and user.role == "admin",
            "pipeline_version": PARITY_VERSION,
            "parity_fingerprint": parity_fingerprint(),
            "coair_sha": os.getenv("COAIR_COMMIT_SHA", "development"),
            "upstream_sha": UPSTREAM_SHA, "streamlit": False,
            "max_workspace_bytes": MAX_WORKSPACE_BYTES,
            "modules": [{"slug": slug, **definition,
                         "parity": MODULE_PARITY.get(slug, {})}
                        for slug, definition in MODULE_DEFINITIONS.items()]}


@router.get("/forensic/sources")
def list_forensic_sources(
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(get_current_project),
):
    _parity_enabled(user)
    return {"sources": ForensicSourceService().list_project_sources(project.project_id)}


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


@router.put("/forensic/workspaces/{workspace_id}/sources")
def replace_workspace_sources(
    workspace_id: str, body: SourceSelectionUpdate,
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(require_project_editor),
):
    _parity_enabled(user)
    store = get_forensic_store()
    if not store.get_workspace(project.project_id, workspace_id):
        raise HTTPException(404, "forensic_workspace_not_found")
    try:
        sources = ForensicSourceService(store).resolve_selection(
            project_id=project.project_id, workspace_id=workspace_id,
            selections=[item.model_dump() for item in body.sources],
        )
        programme_bytes = sum(item["size_bytes"] for item in sources
                              if item["source_kind"] == "programme")
        if programme_bytes > MAX_WORKSPACE_BYTES:
            raise HTTPException(413, "forensic_workspace_size_exceeded")
        value = store.replace_workspace_sources(
            project_id=project.project_id, workspace_id=workspace_id,
            expected_version=body.expected_version, sources=sources,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        message = str(exc)
        status = 409 if "version_conflict" in message or "hash_mismatch" in message else 422
        raise HTTPException(status, message) from exc
    return {
        "workspace": _workspace_public(
            store.get_workspace(project.project_id, workspace_id) or {}
        ),
        "state": store.get_workspace_state(project.project_id, workspace_id),
        "sources": [{key: item[key] for key in item if key != "snapshot_path"}
                    for item in value["sources"]],
        "source_revision": value["source_revision"],
    }


@router.get("/forensic/workspaces/{workspace_id}/state")
def get_workspace_state(
    workspace_id: str, user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(get_current_project),
):
    _parity_enabled(user)
    record = get_forensic_store().get_workspace_state(project.project_id, workspace_id)
    if not record:
        raise HTTPException(404, "forensic_workspace_not_found")
    return record


@router.patch("/forensic/workspaces/{workspace_id}/state")
def patch_workspace_state(
    workspace_id: str, body: WorkspaceStatePatch,
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(require_project_editor),
):
    _parity_enabled(user)
    store = get_forensic_store()
    selected = store.list_workspace_sources(project.project_id, workspace_id)
    programme_ids = {item["source_id"] for item in selected
                     if item["source_kind"] == "programme"}
    if not programme_ids:
        workspace = store.get_workspace(project.project_id, workspace_id)
        programme_ids = set((workspace or {}).get("programme_ids") or [])
    for programme_id in (body.baseline_programme_id, body.current_programme_id):
        if programme_id is not None and programme_id not in programme_ids:
            raise HTTPException(422, "forensic_workspace_programme_role_invalid")
    try:
        return store.update_workspace_state(
            project_id=project.project_id, workspace_id=workspace_id,
            expected_version=body.expected_version,
            patch=_workspace_state_patch(body),
        )
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(409 if "version_conflict" in message else 404, message) from exc


@router.get("/forensic/workspaces/{workspace_id}/modules/{module_slug}")
def get_module_view(
    workspace_id: str, module_slug: str,
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(get_current_project),
):
    _parity_enabled(user)
    if module_slug not in MODULE_DEFINITIONS:
        raise HTTPException(404, "forensic_module_not_found")
    store = get_forensic_store()
    workspace = store.get_workspace(project.project_id, workspace_id)
    state = store.get_workspace_state(project.project_id, workspace_id)
    if not workspace or not state:
        raise HTTPException(404, "forensic_workspace_not_found")
    matching_runs = [run for run in store.list_runs(project.project_id, workspace_id)
                     if run["module_slug"] == module_slug]
    return {
        "workspace": _workspace_public(workspace),
        "state_version": state["version"],
        "state": state["state"],
        "module": {"slug": module_slug, **MODULE_DEFINITIONS[module_slug],
                   "parity": MODULE_PARITY[module_slug]},
        "sources": [{key: value for key, value in item.items() if key != "snapshot_path"}
                    for item in store.list_workspace_sources(project.project_id, workspace_id)],
        "latest_run": _run_public(matching_runs[0], user, project.project_id)
                      if matching_runs else None,
    }


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


@router.post(
    "/forensic/workspaces/{workspace_id}/modules/{module_slug}/actions/{action_slug}",
    status_code=202,
)
def create_module_action(
    workspace_id: str, module_slug: str, action_slug: str, body: ModuleActionRequest,
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(require_project_editor),
):
    """Versioned parity action boundary.

    The first durable action is ``run``.  The parity manifest deliberately
    advertises subsequent analyst/AI/export actions, but an unimplemented
    action is rejected rather than silently mapped to a generic calculation.
    """
    _parity_enabled(user)
    if module_slug not in MODULE_DEFINITIONS:
        raise HTTPException(404, "forensic_module_not_found")
    if body.action != action_slug:
        raise HTTPException(422, "forensic_module_action_mismatch")
    advertised = set(MODULE_PARITY[module_slug].get("actions") or [])
    if action_slug not in advertised:
        raise HTTPException(404, "forensic_module_action_not_found")
    if isinstance(body, ExtractEventsAction):
        if module_slug != "time-impact-analysis":
            raise HTTPException(422, "forensic_module_action_mismatch")
        selected_ids = {item["source_id"] for item in get_forensic_store().list_workspace_sources(
            project.project_id, workspace_id,
        ) if item["source_kind"] != "programme"}
        if not set(body.source_ids).issubset(selected_ids):
            raise HTTPException(422, "forensic_evidence_source_not_selected")
        try:
            return ForensicActionService().extract_tia_events(
                project_id=project.project_id, workspace_id=workspace_id,
                username=user.username, expected_version=body.expected_version,
                source_ids=body.source_ids, query=body.query,
            )
        except ForensicActionError as exc:
            raise HTTPException(422, str(exc)) from exc
        except CreditBalanceExceededError as exc:
            raise HTTPException(402, "credit_balance_exhausted") from exc
        except ValueError as exc:
            raise HTTPException(409 if "version_conflict" in str(exc) else 422,
                                str(exc)) from exc
    if isinstance(body, GenerateNarrativeAction):
        try:
            return ForensicActionService().generate_narrative(
                project_id=project.project_id, workspace_id=workspace_id,
                username=user.username, expected_version=body.expected_version,
                module_slug=module_slug, run_id=body.run_id,
                analyst_instructions=body.analyst_instructions,
            )
        except ForensicActionError as exc:
            raise HTTPException(422, str(exc)) from exc
        except CreditBalanceExceededError as exc:
            raise HTTPException(402, "credit_balance_exhausted") from exc
        except ValueError as exc:
            raise HTTPException(409 if "version_conflict" in str(exc) else 422,
                                str(exc)) from exc
    if isinstance(body, ExtractClauseAction):
        if module_slug != "time-impact-analysis":
            raise HTTPException(422, "forensic_module_action_mismatch")
        selected_ids = {item["source_id"] for item in get_forensic_store().list_workspace_sources(
            project.project_id, workspace_id,
        ) if item["source_kind"] != "programme"}
        if not set(body.source_ids).issubset(selected_ids):
            raise HTTPException(422, "forensic_evidence_source_not_selected")
        try:
            return ForensicActionService().extract_contract_clauses(
                project_id=project.project_id, workspace_id=workspace_id,
                username=user.username, expected_version=body.expected_version,
                source_ids=body.source_ids,
            )
        except ForensicActionError as exc:
            raise HTTPException(422, str(exc)) from exc
        except CreditBalanceExceededError as exc:
            raise HTTPException(402, "credit_balance_exhausted") from exc
        except ValueError as exc:
            raise HTTPException(409 if "version_conflict" in str(exc) else 422,
                                str(exc)) from exc
    if isinstance(body, RecommendFragnetAction):
        if module_slug != "time-impact-analysis":
            raise HTTPException(422, "forensic_module_action_mismatch")
        try:
            return ForensicActionService().recommend_fragnet(
                project_id=project.project_id, workspace_id=workspace_id,
                username=user.username, expected_version=body.expected_version,
                programme_id=body.programme_id,
                event_record=body.event.model_dump(),
            )
        except ForensicActionError as exc:
            raise HTTPException(422, str(exc)) from exc
        except CreditBalanceExceededError as exc:
            raise HTTPException(402, "credit_balance_exhausted") from exc
        except ValueError as exc:
            raise HTTPException(409 if "version_conflict" in str(exc) else 422,
                                str(exc)) from exc
    if isinstance(body, RecommendLogicAction):
        if module_slug != "time-impact-analysis":
            raise HTTPException(422, "forensic_module_action_mismatch")
        try:
            return ForensicActionService().recommend_logic(
                project_id=project.project_id, workspace_id=workspace_id,
                username=user.username, expected_version=body.expected_version,
                programme_id=body.programme_id, event_record=body.event.model_dump(),
                fragnet_rows=[item.model_dump(by_alias=True) for item in body.fragnet],
            )
        except ForensicActionError as exc:
            raise HTTPException(422, str(exc)) from exc
        except CreditBalanceExceededError as exc:
            raise HTTPException(402, "credit_balance_exhausted") from exc
        except ValueError as exc:
            raise HTTPException(409 if "version_conflict" in str(exc) else 422,
                                str(exc)) from exc
    if isinstance(body, ReviewSequenceAction):
        if module_slug != "sequence-coding":
            raise HTTPException(422, "forensic_module_action_mismatch")
        try:
            return ForensicActionService().review_sequence_mapping(
                project_id=project.project_id, workspace_id=workspace_id,
                username=user.username, expected_version=body.expected_version,
                programme_id=body.programme_id,
                rows=[item.model_dump() for item in body.rows],
            )
        except ForensicActionError as exc:
            raise HTTPException(422, str(exc)) from exc
        except CreditBalanceExceededError as exc:
            raise HTTPException(402, "credit_balance_exhausted") from exc
        except ValueError as exc:
            raise HTTPException(409 if "version_conflict" in str(exc) else 422,
                                str(exc)) from exc
    if not isinstance(body, RunModuleAction):
        raise HTTPException(501, "forensic_module_action_not_implemented")
    if body.parameters.kind != module_slug:
        raise HTTPException(422, "forensic_module_parameter_mismatch")
    store = get_forensic_store()
    state = store.get_workspace_state(project.project_id, workspace_id)
    if not state:
        raise HTTPException(404, "forensic_workspace_not_found")
    if int(state["version"]) != body.expected_version:
        raise HTTPException(409, "forensic_workspace_state_version_conflict")
    parameters = body.parameters.model_dump(by_alias=True)
    parameters.pop("kind", None)
    parameters["_ai_narrative"] = body.ai_narrative
    try:
        run = store.enqueue_run(
            project_id=project.project_id, workspace_id=workspace_id,
            username=user.username, module_slug=module_slug, parameters=parameters,
        )
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(409 if "changed" in message else 404, message) from exc
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
