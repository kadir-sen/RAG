"""Render a report section to downloadable files.

One public signature (the structured input compose_section takes), two internal
strategies: PDF reuses the templater's HTML, DOCX walks the structured input.
Callers cannot tell the difference and neither duplicates the section layout.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from src.programme_tools.schemas import ArtifactBlob

from .artifacts import persist_blobs, safe_filename

logger = logging.getLogger(__name__)

FORMATS = ("pdf", "docx")

_RENDERERS = {
    "pdf": ("section_pdf", "render_section_pdf",
            "application/pdf"),
    "docx": ("section_docx", "render_section_docx", ""),
}


def _slug(title: str, section_number: str) -> str:
    base = f"{section_number}_{title}" if section_number else (title or "section")
    return safe_filename(base.strip().replace(" ", "_")).strip("._") or "section"


def render_section(fmt: str, title: str, narrative_markdown: str, **kw
                   ) -> Tuple[Optional[bytes], str]:
    """Render one format. Returns (bytes|None, reason)."""
    spec = _RENDERERS.get(fmt)
    if spec is None:
        return None, f"unknown export format '{fmt}'"
    module_name, func_name, _ = spec
    try:
        import importlib
        module = importlib.import_module(f"src.export.{module_name}")
        data = getattr(module, func_name)(title, narrative_markdown, **kw)
        return data, ""
    except Exception as e:
        logger.warning(f"[Export] {fmt} render failed: {e}")
        return None, f"{fmt} export failed: {e}"


def section_artifacts(title: str, narrative_markdown: str, *,
                      run_id: Optional[str] = None,
                      formats: Tuple[str, ...] = FORMATS,
                      tables: Optional[List[Dict[str, Any]]] = None,
                      sources: Optional[List[Dict[str, Any]]] = None,
                      caveats: Optional[List[str]] = None,
                      validation: Optional[Dict[str, Any]] = None,
                      section_number: str = "") -> List[dict]:
    """Render + persist a section. Returns ToolResult.artifacts-shaped dicts,
    which helpers.artifact_blocks() already consumes unchanged.

    Best-effort by design: an export failure costs the download, never the
    section the user asked for. run_id defaults to a fresh id, matching
    programme_tools.run_tool's contract, so adapters need no plumbing.
    """
    kw = dict(tables=tables, sources=sources, caveats=caveats,
              validation=validation, section_number=section_number)
    stem = _slug(title, section_number)

    blobs: List[ArtifactBlob] = []
    for fmt in formats:
        data, reason = render_section(fmt, title, narrative_markdown, **kw)
        if data:
            blobs.append(ArtifactBlob(filename=f"{stem}.{fmt}", kind=fmt,
                                      data=data))
        else:
            logger.info(f"[Export] skipping {fmt}: {reason}")
    if not blobs:
        return []

    try:
        return persist_blobs(blobs, run_id or uuid.uuid4().hex[:12])
    except Exception as e:
        logger.warning(f"[Export] artifact persist failed: {e}")
        return []
