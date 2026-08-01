"""Request/job scoped project identity shared by storage and retrieval layers."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Optional


current_project_id_var: ContextVar[str] = ContextVar("project_id", default="")
current_project_role_var: ContextVar[str] = ContextVar("project_role", default="")


def get_current_project_id() -> str:
    return (current_project_id_var.get() or "").strip()


def set_current_project(project_id: str, role: str = "") -> None:
    current_project_id_var.set((project_id or "").strip())
    current_project_role_var.set((role or "").strip())


def get_current_project_role() -> Optional[str]:
    return current_project_role_var.get() or None


__all__ = [
    "current_project_id_var",
    "current_project_role_var",
    "get_current_project_id",
    "get_current_project_role",
    "set_current_project",
]
