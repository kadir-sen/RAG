"""Admin-only user management endpoints. All deps gate on `require_admin`."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.security import UserContext, require_admin
from src.user_store import UserStore, get_user_store


router = APIRouter()


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6)
    display_name: Optional[str] = None
    role: str = "user"
    token_limit: int = 1_000_000
    features: Dict[str, bool] = Field(default_factory=dict)


class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    token_limit: Optional[int] = None
    features: Optional[Dict[str, bool]] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


def _enriched(store: UserStore, record: Dict[str, Any]) -> Dict[str, Any]:
    usage = store.get_usage(record["username"])
    return {
        **record,
        "used_tokens": usage["used_tokens"],
        "percent_remaining": usage["percent_remaining"],
        "total_calls": usage["total_calls"],
    }


@router.get("/admin/users")
async def list_users(
    _admin: UserContext = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
):
    return {"users": [_enriched(store, u) for u in store.list_users()]}


@router.post("/admin/users", status_code=201)
async def create_user(
    req: CreateUserRequest,
    _admin: UserContext = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
):
    try:
        record = store.create_user(
            username=req.username.strip(),
            password=req.password,
            display_name=req.display_name,
            role=req.role,
            token_limit=req.token_limit,
            features=req.features,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _enriched(store, record)


@router.patch("/admin/users/{username}")
async def update_user(
    username: str,
    req: UpdateUserRequest,
    _admin: UserContext = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
):
    payload = {k: v for k, v in req.model_dump().items() if v is not None}
    try:
        record = store.update_user(username, **payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not record:
        raise HTTPException(404, "user_not_found")
    return _enriched(store, record)


@router.post("/admin/users/{username}/reset-usage")
async def reset_usage(
    username: str,
    _admin: UserContext = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
):
    if not store.get_user(username):
        raise HTTPException(404, "user_not_found")
    return store.reset_usage(username)


@router.delete("/admin/users/{username}", status_code=204)
async def delete_user(
    username: str,
    _admin: UserContext = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
):
    if not store.delete_user(username, soft=True):
        raise HTTPException(404, "user_not_found")
    return None
