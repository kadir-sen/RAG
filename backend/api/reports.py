"""AI generation endpoints behind the existing Chronology and Forensic blocks."""

from __future__ import annotations

from pathlib import Path
from dataclasses import asdict
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from backend.api._docx import docx_response
from backend.core.projects import ProjectContext, get_current_project, require_project_editor
from backend.core.security import UserContext, get_current_user, require_admin
from backend.tasks.ingestion_jobs import get_ingestion_job_store
from backend.tasks.report_jobs import get_report_job_store
from src.docx_kit import safe_filename


router = APIRouter()


class ChronologyGenerateRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=1000)
    date_from: str = ""
    date_to: str = ""
    parties: List[str] = Field(default_factory=list, max_length=30)
    preparation_id: str = Field(default="", max_length=64)
    # No twenty-document ceiling: it was a stand-in for cost control that did
    # not control cost, since a document here runs from 16 to 290,294
    # characters. The evidence budget bounds the work; this bound only stops an
    # absurd request. The analyst's selection is read in full within that budget,
    # shared evenly across their chosen documents.
    source_doc_ids: List[str] = Field(default_factory=list, max_length=500)

    @field_validator("topic")
    @classmethod
    def topic_is_not_whitespace(cls, value: str) -> str:
        clean = value.strip()
        if len(clean) < 3:
            raise ValueError("chronology_topic_required")
        return clean


class ForensicGenerateRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=1000)
    date_from: str = ""
    date_to: str = ""
    parties: List[str] = Field(default_factory=list, max_length=30)
    status: str = "Draft"
    toolkit_artifact_ids: List[str] = Field(default_factory=list, max_length=30)


class ToolkitEvidenceRequest(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    methodology: str = Field(min_length=3, max_length=300)
    findings: List[str] = Field(min_length=1, max_length=100)
    source_doc_ids: List[str] = Field(default_factory=list, max_length=500)


class ForensicDraftUpdate(BaseModel):
    sections: Dict[str, List[dict]]
    issue: bool = False


def _assert_ready(project_id: str) -> None:
    summary = get_ingestion_job_store().project_summary(project_id)
    if summary["queued"] or summary["processing"]:
        raise HTTPException(409, {
            "error": "project_processing",
            "queued": summary["queued"],
            "processing": summary["processing"],
            "eta_seconds": summary["eta_seconds"],
        })
    from src.document_registry import get_document_registry
    if get_document_registry().get_completed(project_id=project_id):
        return
    try:
        from src.chunk_store import get_chunk_store
        row = get_chunk_store().connection().execute(
            "SELECT 1 FROM chunks WHERE project_id=? LIMIT 1", [project_id]
        ).fetchone()
        if row:
            return
    except Exception:
        pass
    raise HTTPException(409, "project_has_no_ready_documents")


def _assert_chronology_enabled() -> None:
    from src.config import CHRONOLOGY_PIPELINE_VERSION
    if CHRONOLOGY_PIPELINE_VERSION not in ("v2", "v3"):
        raise HTTPException(503, "chronology_disabled")
    try:
        from src.chronology_prompts import validate_chronology_runtime
        validate_chronology_runtime()
    except Exception as exc:
        raise HTTPException(503, "chronology_configuration_invalid") from exc


def _chronology_pipeline(username: str) -> str:
    from src.config import CHRONOLOGY_V3_DEMO_ENABLED
    from src.user_store import get_user_store
    account = get_user_store().billing.summary(username)
    if CHRONOLOGY_V3_DEMO_ENABLED and account.get("plan_type") == "demo":
        return "chronology-v3"
    # V3 rollout is deliberately demo-only until the solicitor/golden acceptance
    # suite has completed; environment drift must not move admin/Edinburgh jobs.
    return "chronology-v2"


_PUBLIC_ERRORS = {
    "model_output_incomplete": "The model response was incomplete. Retry will resume this report.",
    "source_verification_failed": "The draft did not pass source verification.",
    "no_evidence": "No project evidence was found for this topic.",
    "insufficient_evidence": "The selected records do not establish a chronology.",
    "research_budget_exhausted": "The research budget was exhausted before verification.",
    "chronology_preparation_expired": "The source preparation expired. Review the sources again.",
    "source_document_not_in_project": "A selected source is no longer available in this project.",
    "source_document_selection_invalid": "The selected source set is no longer valid.",
    "provider_rate_limited": "The model provider is temporarily busy. Please retry.",
    "provider_timeout": "The model provider did not complete this stage in time.",
    "provider_authentication_failed": "The model service is not configured correctly.",
    "provider_safety_blocked": "The model service declined this request.",
    "provider_billing_failed": "The model service account is unavailable.",
    "provider_schema_rejected": "The report schema was rejected by the model service.",
    "credit_balance_exhausted": "Credit balance exhausted.",
    "report_generation_failed": "The chronology could not be completed.",
}


def _public(job: dict) -> dict:
    value = {k: v for k, v in job.items() if k not in ("request", "docx_path")}
    if value.get("status") in ("failed", "credit_balance_exhausted"):
        code = str(value.get("error_code") or "report_generation_failed")
        value["error"] = _PUBLIC_ERRORS.get(code, _PUBLIC_ERRORS["report_generation_failed"])
    result = value.get("result")
    if isinstance(result, dict):
        if value.get("module") == "chronology" or "entries" in result:
            # Deliberate allow-list: future diagnostics, token or monetary fields
            # cannot accidentally become part of the normal chronology contract.
            #
            # coverage_status and partial_reasons are on it on purpose. A report
            # that read only part of its evidence has to be able to say so; the
            # alternative is what production did — present a three-event record
            # with no indication that anything was missing.
            value["result"] = {
                key: result[key] for key in
                ("entries", "evidence", "coverage_status", "partial_reasons")
                if key in result
            }
        else:
            value["result"] = {key: item for key, item in result.items() if key not in {
                "research_audit", "verification_audit", "research_questions",
                "selected_doc_ids", "coverage", "render_audit",
                "model", "prompt_version", "pipeline_version", "removed_claims", "audit",
            }}
    value.pop("coverage_status", None)
    return value


@router.post("/chronology/source-preview")
def preview_chronology_sources(
    body: ChronologyGenerateRequest,
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(require_project_editor),
):
    _assert_chronology_enabled()
    _assert_ready(project.project_id)
    from src.ai_reports import retrieve_evidence
    from src.chronology_v2 import prepare_chronology_query, source_preview
    from src.llm_client import begin_chronology_call_budget, end_chronology_call_budget
    begin_chronology_call_budget()
    try:
        prepared = prepare_chronology_query(
            body.topic, date_from=body.date_from, date_to=body.date_to,
            parties=body.parties, project_id=project.project_id,
        )
        result = source_preview(project.project_id, prepared, retrieve_evidence)
    finally:
        end_chronology_call_budget()
    return get_report_job_store().create_preparation(
        project_id=project.project_id, username=user.username,
        request={
            "topic": body.topic, "date_from": body.date_from,
            "date_to": body.date_to, "parties": body.parties,
        },
        result=result,
    )


@router.post("/chronology/generate", status_code=202)
def generate_chronology_report(
    body: ChronologyGenerateRequest,
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(require_project_editor),
):
    _assert_chronology_enabled()
    _assert_ready(project.project_id)
    from src.user_store import get_user_store
    account = get_user_store().billing.get_account(user.username)
    if account and account.get("plan_type") == "demo":
        get_user_store().billing.enforce_credits(user.username)
    preparation = None
    if body.preparation_id:
        preparation = get_report_job_store().get_preparation(
            body.preparation_id, project.project_id, user.username,
        )
        if not preparation:
            raise HTTPException(409, "chronology_preparation_expired")
        allowed = {str(row.get("doc_id") or "") for row in preparation.get("documents", [])}
        if any(doc_id not in allowed for doc_id in body.source_doc_ids):
            raise HTTPException(422, "source_document_not_in_preparation")
    pipeline_version = _chronology_pipeline(user.username)
    job = get_report_job_store().enqueue(
        project_id=project.project_id, username=user.username, module="chronology",
        title=body.topic,
        request={
            "project_name": project.name, "topic": body.topic,
            "date_from": body.date_from, "date_to": body.date_to,
            "parties": body.parties,
            "preparation_id": body.preparation_id,
            "source_doc_ids": body.source_doc_ids,
        }, pipeline_version=pipeline_version,
    )
    return _public(job)


@router.post("/forensic/generate", status_code=202)
def generate_forensic_report(
    body: ForensicGenerateRequest,
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(require_project_editor),
):
    status = body.status.strip().title()
    if status not in ("Draft", "Issue"):
        raise HTTPException(422, "status must be Draft or Issue")
    _assert_ready(project.project_id)
    job = get_report_job_store().enqueue(
        project_id=project.project_id, username=user.username, module="forensic",
        title=body.topic,
        request={
            "project_name": project.name, "topic": body.topic,
            "date_from": body.date_from, "date_to": body.date_to,
            "parties": body.parties, "status": status,
            "toolkit_artifact_ids": body.toolkit_artifact_ids,
        },
    )
    return _public(job)


@router.post("/forensic/toolkit-evidence", status_code=201)
def register_toolkit_evidence(
    body: ToolkitEvidenceRequest,
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(require_project_editor),
):
    from src.document_registry import get_document_registry
    from src.toolkit_evidence_store import get_toolkit_evidence_store
    registry = get_document_registry()
    for doc_id in body.source_doc_ids:
        record = registry.get(doc_id)
        if not record or (getattr(record, "project_id", "") or "") != project.project_id:
            raise HTTPException(422, f"Toolkit source is not in this project: {doc_id}")
    return get_toolkit_evidence_store().create(
        project_id=project.project_id, title=body.title,
        methodology=body.methodology,
        findings=[value.strip() for value in body.findings if value.strip()],
        source_doc_ids=body.source_doc_ids, created_by=user.username,
    )


@router.get("/forensic/toolkit-evidence")
def list_toolkit_evidence(project: ProjectContext = Depends(get_current_project)):
    from src.toolkit_evidence_store import get_toolkit_evidence_store
    return {"artifacts": get_toolkit_evidence_store().list_project(project.project_id)}


@router.get("/reports")
def list_reports(
    module: str = Query(""),
    project: ProjectContext = Depends(get_current_project),
):
    if module and module not in ("chronology", "forensic"):
        raise HTTPException(422, "unsupported report module")
    return {"reports": [_public(j) for j in get_report_job_store().list_project(
        project.project_id, module=module,
    )]}


@router.get("/reports/{job_id}")
def get_report(job_id: str, project: ProjectContext = Depends(get_current_project)):
    job = get_report_job_store().get(job_id, project.project_id)
    if not job:
        raise HTTPException(404, "report_not_found")
    return _public(job)


@router.post("/reports/{job_id}/retry", status_code=202)
def retry_report(
    job_id: str,
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(require_project_editor),
):
    store = get_report_job_store()
    current = store.get(job_id, project.project_id)
    if not current:
        raise HTTPException(404, "report_not_found")
    if current["status"] == "credit_balance_exhausted":
        from src.user_store import get_user_store
        try:
            get_user_store().billing.enforce_credits(user.username)
        except Exception as exc:
            raise HTTPException(402, "credit_balance_exhausted") from exc
    retried = store.retry(job_id, project.project_id)
    if not retried:
        raise HTTPException(409, "report_not_retryable")
    return _public(retried)


@router.get("/admin/reports/{job_id}/diagnostics")
def report_diagnostics(
    job_id: str,
    _admin: UserContext = Depends(require_admin),
):
    store = get_report_job_store()
    # Admin diagnostics intentionally searches across projects without exposing
    # this capability on the normal project-scoped report endpoint.
    with store._connect() as conn:
        row = conn.execute("SELECT * FROM report_jobs WHERE job_id=?", [job_id]).fetchone()
    if not row:
        raise HTTPException(404, "report_not_found")
    job = store._row(row)
    from src.billing_store import get_billing_store
    from src.model_profiles import TASK_PROFILES
    from src.run_store import get_run_store
    return {
        "job_id": job_id, "project_id": job["project_id"],
        "pipeline_version": job.get("pipeline_version"),
        "prompt_version": (job.get("result") or {}).get("prompt_version"),
        "model": (job.get("result") or {}).get("model"),
        "stage": job.get("stage"), "error_code": job.get("error_code"),
        "technical_error": job.get("error"), "request": job.get("request"),
        "coverage_status": job.get("coverage_status"),
        "research_audit": (job.get("result") or {}).get("research_audit"),
        "verification_audit": (job.get("result") or {}).get("verification_audit"),
        "render_audit": (job.get("result") or {}).get("render_audit"),
        "steps": store.list_steps(job_id, include_output=True),
        "llm_audit": get_run_store().details(job_id),
        "billing": get_billing_store().job_usage(job_id),
        "model_profiles": {
            name: asdict(profile) for name, profile in TASK_PROFILES.items()
            if name.startswith("chronology_") or name in ("research_plan", "rerank")
        },
    }


@router.get("/reports/{job_id}/sources/{source_id}")
def resolve_report_source(
    job_id: str,
    source_id: str,
    project: ProjectContext = Depends(get_current_project),
):
    """Resolve a footnote/source back to a record inside the selected project."""
    job = get_report_job_store().get(job_id, project.project_id)
    if not job or job["status"] != "ready":
        raise HTTPException(404, "report_not_found")
    source = next((item for item in (job.get("result") or {}).get("evidence", [])
                   if item.get("source_id") == source_id), None)
    if not source:
        raise HTTPException(404, "source_not_found")
    from src.document_registry import get_document_registry
    registry = get_document_registry()
    record = registry.get(str(source.get("doc_id") or ""))
    if record and (getattr(record, "project_id", "") or "") == project.project_id:
        return {"source": source, "record": {
            "doc_id": record.doc_id, "file_name": record.file_name,
            "file_type": record.file_type, "status": record.status,
        }}
    # Vectors-only records are still resolvable, but only through a scoped chunk.
    try:
        from src.chunk_store import get_chunk_store
        row = get_chunk_store().connection().execute(
            "SELECT doc_id,file_name,page_number FROM chunks WHERE project_id=? "
            "AND (doc_id=? OR file_name=?) LIMIT 1",
            [project.project_id, source.get("doc_id"), source.get("file_name")],
        ).fetchone()
        if row:
            return {"source": source, "record": {
                "doc_id": row[0], "file_name": row[1], "page": row[2],
                "status": "completed",
            }}
    except Exception:
        pass
    if source.get("kind") == "toolkit":
        return {"source": source, "record": {"status": "toolkit-evidence"}}
    raise HTTPException(409, "source_record_no_longer_resolves")


@router.patch("/reports/{job_id}/draft")
def update_forensic_draft(
    job_id: str,
    body: ForensicDraftUpdate,
    project: ProjectContext = Depends(require_project_editor),
):
    """Save reviewed forensic text and optionally promote it to Issue."""
    from src.evidence_model import EvidenceItem, VerifiedClaim
    from src.report_docx import FORENSIC_SECTIONS, build_forensic_report_docx

    store = get_report_job_store()
    job = store.get(job_id, project.project_id)
    if not job or job["module"] != "forensic" or job["status"] != "ready":
        raise HTTPException(404, "forensic_draft_not_found")
    result = dict(job.get("result") or {})
    evidence = [EvidenceItem(**item) for item in result.get("evidence", [])]
    valid_sources = {item.source_id for item in evidence}
    sections: Dict[str, List[VerifiedClaim]] = {name: [] for name in FORENSIC_SECTIONS}
    for name, raw_claims in body.sections.items():
        if name not in sections:
            raise HTTPException(422, f"unsupported section: {name}")
        for raw in raw_claims:
            claim = VerifiedClaim(
                text=str(raw.get("text") or "").strip(),
                source_ids=[str(x) for x in raw.get("source_ids", [])],
                supported=True,
                confidence=str(raw.get("confidence") or "low"),
                counter_source_ids=[str(x) for x in raw.get("counter_source_ids", [])],
                missing_records=[str(x) for x in raw.get("missing_records", [])],
            )
            if not claim.text:
                continue
            if not claim.source_ids or any(sid not in valid_sources for sid in (
                claim.source_ids + claim.counter_source_ids
            )):
                raise HTTPException(422, "Every edited claim requires resolvable project sources")
            sections[name].append(claim)
    if body.issue and any(not sections[name] for name in FORENSIC_SECTIONS):
        raise HTTPException(409, "Issue requires a verified claim in every mandatory section")

    status = "Issue" if body.issue else "Draft"
    blob, audit = build_forensic_report_docx(
        project_name=str((job.get("request") or {}).get("project_name") or project.name),
        title=job["title"], sections=sections, evidence=evidence, status=status,
        audit_metadata={"prompt": "evidence-report-v1", "review": "human-edited"},
    )
    if audit.unresolved_source_ids or (body.issue and audit.footnote_records == 0):
        raise HTTPException(409, "Issue failed footnote verification")
    path = Path(job["docx_path"])
    path.write_bytes(blob)
    result.update({
        "sections": {name: [asdict(claim) for claim in claims]
                     for name, claims in sections.items()},
        "audit": asdict(audit), "status": status, "human_reviewed": True,
    })
    store.replace_ready_result(job_id, result, str(path))
    return _public(store.get(job_id, project.project_id) or job)


@router.get("/reports/{job_id}/document")
def download_report(job_id: str, project: ProjectContext = Depends(get_current_project)):
    job = get_report_job_store().get(job_id, project.project_id)
    if not job or job["status"] != "ready" or not job.get("docx_path"):
        raise HTTPException(404, "report_document_not_ready")
    path = Path(job["docx_path"])
    if not path.is_file():
        raise HTTPException(500, "report_document_missing")
    return docx_response(
        path.read_bytes(), safe_filename(job["module"], job["title"]) + ".docx",
    )
