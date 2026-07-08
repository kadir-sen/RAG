"""Tiny indirection so tests can monkeypatch the artifacts directory without
touching src.config (which creates real directories at import time)."""

from __future__ import annotations

from pathlib import Path


def artifacts_dir() -> Path:
    from src.config import ARTIFACTS_DIR
    return ARTIFACTS_DIR
