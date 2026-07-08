"""Shared XER loading for the programme adapters.

Adapters receive plain record dicts ({"file_name", "file_path", "doc_id"})
so they stay unit-testable without the document registry; the router handler
resolves registry records into this shape.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


class XerLoadError(Exception):
    """One file failed to load/parse; message is user-safe."""


def load_xer_files(records: List[Dict[str, Any]]) -> List[Tuple[str, Any]]:
    """Parse each record's file into (file_name, XerData), preserving order.

    Raises XerLoadError with a user-facing message on the FIRST bad file —
    the computation guard turns this into a failed ToolResult, never a trace.
    """
    from ..vendor.dcma import parse_xer

    out: List[Tuple[str, Any]] = []
    for rec in records:
        name = rec.get("file_name") or "unknown.xer"
        path = rec.get("file_path") or ""
        p = Path(path)
        if not p.exists() or p.stat().st_size == 0:
            raise XerLoadError(f"Programme file '{name}' is missing or empty on disk.")
        try:
            data = parse_xer(p.read_bytes())
        except Exception as e:
            logger.warning(f"[ProgrammeTools] parse failed for {name}: {e}")
            raise XerLoadError(
                f"'{name}' could not be parsed as a Primavera P6 XER export."
            ) from e
        if not data.raw_tables.get("TASK") or not data.projects:
            raise XerLoadError(
                f"'{name}' does not appear to be a valid P6 XER export "
                "(no TASK table or project data found)."
            )
        out.append((name, data))
    return out
