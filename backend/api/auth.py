"""POST /api/auth/login — JWT issuance + GET /api/auth/me — session probe."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.core.security import (
    UserContext,
    create_access_token,
    get_current_user,
)
from src.user_store import UserStore, get_user_store


router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


def _user_payload(record: Dict[str, Any], usage: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "username": record["username"],
        "display_name": record["display_name"],
        "role": record["role"],
        "features": record["features"],
        "token_limit": record["token_limit"],
        "used_tokens": usage["used_tokens"],
        "percent_remaining": usage["percent_remaining"],
    }


@router.post("/auth/login")
async def login(
    req: LoginRequest,
    store: UserStore = Depends(get_user_store),
):
    record = store.verify_password(req.username.strip(), req.password)
    if not record:
        raise HTTPException(401, "invalid_credentials")
    usage = store.get_usage(record["username"])
    token = create_access_token(record["username"], record["role"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _user_payload(record, usage),
    }


@router.get("/auth/me")
async def me(
    user: UserContext = Depends(get_current_user),
    store: UserStore = Depends(get_user_store),
):
    record = store.get_user(user.username)
    if not record:
        raise HTTPException(401, "unknown_user")
    usage = store.get_usage(user.username)
    return {"user": _user_payload(record, usage)}


@router.post("/auth/logout")
async def logout():
    return {"ok": True}
