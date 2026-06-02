"""
JWT auth + FastAPI dependencies + a request-scoped current-user contextvar.

The contextvar is set by `get_current_user` for every authenticated request and
consumed by `src/llm_client.py` to attribute token usage to the active user
without rewiring every call site.
"""
from __future__ import annotations

import os
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

import jwt
from fastapi import Depends, Header, HTTPException, status

from src.user_store import UserStore, get_user_store


# ── Settings ────────────────────────────────────────────────

JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_TTL_DAYS = int(os.getenv("JWT_TTL_DAYS", "7"))


def _require_secret() -> str:
    if not JWT_SECRET:
        raise RuntimeError(
            "JWT_SECRET is not set. Generate one with "
            "`python -c \"import secrets;print(secrets.token_urlsafe(48))\"` "
            "and add it to .env."
        )
    return JWT_SECRET


# ── User context ────────────────────────────────────────────

@dataclass
class UserContext:
    """Decoded current user for an authenticated request."""

    username: str
    role: str
    display_name: str
    features: Dict[str, bool]
    token_limit: int


current_user_var: ContextVar[Optional[UserContext]] = ContextVar(
    "current_user", default=None
)


def get_current_username() -> Optional[str]:
    """Helper used by llm_client to attribute usage. None for unauthenticated work."""
    user = current_user_var.get()
    return user.username if user else None


# ── Token helpers ───────────────────────────────────────────

def hash_password(plain: str) -> str:
    import bcrypt

    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    import bcrypt

    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(username: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=JWT_TTL_DAYS)).timestamp()),
    }
    return jwt.encode(payload, _require_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Dict[str, Any]:
    return jwt.decode(token, _require_secret(), algorithms=[JWT_ALGORITHM])


# ── FastAPI dependencies ────────────────────────────────────

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="not_authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def _bearer_token(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _UNAUTHORIZED
    return authorization.split(" ", 1)[1].strip()


def get_current_user(
    authorization: Optional[str] = Header(default=None),
    store: UserStore = Depends(get_user_store),
) -> UserContext:
    """Resolve the active user from a Bearer JWT. Sets the contextvar as a side effect."""
    token = _bearer_token(authorization)
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(401, "token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(401, "invalid_token") from exc

    username = payload.get("sub")
    if not username:
        raise _UNAUTHORIZED

    record = store.get_user(username)
    if not record:
        raise HTTPException(401, "unknown_user")
    if not record["is_active"]:
        raise HTTPException(403, "account_disabled")

    user = UserContext(
        username=record["username"],
        role=record["role"],
        display_name=record["display_name"],
        features=record["features"],
        token_limit=record["token_limit"],
    )
    current_user_var.set(user)
    return user


def require_admin(user: UserContext = Depends(get_current_user)) -> UserContext:
    if user.role != "admin":
        raise HTTPException(403, "admin_required")
    return user


def require_feature(feature_name: str) -> Callable[[UserContext], UserContext]:
    """Dependency factory: 403 if `feature_name` is not enabled for the user."""

    def _checker(user: UserContext = Depends(get_current_user)) -> UserContext:
        if not user.features.get(feature_name, False):
            raise HTTPException(403, f"feature_not_available:{feature_name}")
        return user

    return _checker


__all__ = [
    "UserContext",
    "current_user_var",
    "get_current_username",
    "hash_password",
    "verify_password",
    "create_access_token",
    "decode_token",
    "get_current_user",
    "require_admin",
    "require_feature",
    "JWT_SECRET",
]
