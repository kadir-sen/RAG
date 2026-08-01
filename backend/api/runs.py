"""Per-query cost, step and latency history."""

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.core.projects import ProjectContext, get_current_project
from backend.core.security import UserContext, get_current_user
from src.run_store import get_run_store


router = APIRouter()


@router.get("/runs")
def list_runs(
    limit: int = Query(200, ge=1, le=1000),
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(get_current_project),
):
    runs = get_run_store().recent(
        project_id=project.project_id, username=user.username,
        admin=user.role == "admin", limit=limit,
    )
    # Legacy interactions predate run_id/project correlation. Preserve them for
    # admins as explicitly unassigned, with unknown metrics rather than false 0s.
    if user.role == "admin" and len(runs) < limit:
        try:
            from src.interaction_log import get_interaction_log
            for old in get_interaction_log().recent(limit=limit - len(runs)):
                runs.append({
                    "run_id": f"legacy_{old['interaction_id']}", "project_id": None,
                    "username": old.get("username"), "module": "chatbot",
                    "query": old.get("query"), "route": old.get("route"),
                    "status": "completed", "created_at": old.get("ts"),
                    "completed_at": None, "latency_ms": None, "source_count": len(old.get("source_files") or []),
                    "footnote_count": None, "verification": old.get("verdict"),
                    "metrics_complete": False, "total_steps": None,
                    "successful_steps": None, "failed_steps": None, "fallback_steps": None,
                    "llm_call_count": None, "input_tokens": None, "output_tokens": None,
                    "reasoning_tokens": None, "cached_tokens": None, "cost_usd": None,
                })
        except Exception:
            pass
    runs.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return {"runs": runs[:limit]}


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    project: ProjectContext = Depends(get_current_project),
):
    value = get_run_store().details(run_id, project_id=project.project_id)
    if not value:
        raise HTTPException(404, "run_not_found")
    return value
