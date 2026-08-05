"""Admin-only user management endpoints. All deps gate on `require_admin`."""

from __future__ import annotations

from typing import Any, Dict, Optional, Literal

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
    plan_type: Literal["demo", "legacy"] = "demo"
    initial_credits: float = Field(default=1000, ge=0)
    markup_percent: float = Field(default=30, ge=0, le=1000)
    storage_limit_bytes: int = Field(default=30_000_000_000, ge=0)
    model_policy: str = "demo-tiered-quality-v2"
    provider_key_ref: str = Field(default="", max_length=64)


class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    token_limit: Optional[int] = None
    features: Optional[Dict[str, bool]] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None
    plan_type: Optional[Literal["demo", "legacy"]] = None
    markup_percent: Optional[float] = Field(default=None, ge=0, le=1000)
    storage_limit_bytes: Optional[int] = Field(default=None, ge=0)
    model_policy: Optional[str] = None
    provider_key_ref: Optional[str] = Field(default=None, max_length=64)


def _enriched(store: UserStore, record: Dict[str, Any]) -> Dict[str, Any]:
    usage = store.get_billing_summary(record["username"])
    return {
        **record,
        "used_tokens": usage["used_tokens"],
        "percent_remaining": usage["percent_remaining"],
        "total_calls": usage["total_calls"],
        **{key: value for key, value in usage.items() if key not in {
            "username", "used_tokens", "token_limit", "percent_remaining",
            "prompt_tokens", "completion_tokens", "total_calls",
        }},
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
            plan_type="legacy" if req.role == "admin" else req.plan_type,
            initial_credits=0 if req.role == "admin" else req.initial_credits,
            markup_percent=req.markup_percent,
            storage_limit_bytes=0 if req.role == "admin" else req.storage_limit_bytes,
            model_policy="" if req.role == "admin" else req.model_policy,
            provider_key_ref="" if req.role == "admin" else req.provider_key_ref,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _enriched(store, record)


class CreditAdjustmentRequest(BaseModel):
    credits: float
    reason: str = Field(..., min_length=3, max_length=500)
    idempotency_key: str = Field(default="", max_length=120)


@router.post("/admin/users/{username}/credits")
async def adjust_credits(
    username: str,
    req: CreditAdjustmentRequest,
    _admin: UserContext = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
):
    if not store.get_user(username):
        raise HTTPException(404, "user_not_found")
    try:
        return store.billing.adjust_credits(
            username, req.credits, req.reason, idempotency_key=req.idempotency_key,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.patch("/admin/users/{username}")
async def update_user(
    username: str,
    req: UpdateUserRequest,
    _admin: UserContext = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
):
    raw = {k: v for k, v in req.model_dump().items() if v is not None}
    billing_keys = {
        "plan_type", "markup_percent", "storage_limit_bytes", "model_policy",
        "provider_key_ref",
    }
    payload = {k: v for k, v in raw.items() if k not in billing_keys}
    try:
        record = store.update_user(username, **payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not record:
        raise HTTPException(404, "user_not_found")
    try:
        store.billing.update_account(
            username, **{k: v for k, v in raw.items() if k in billing_keys}
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
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
