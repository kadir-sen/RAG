"""Multi-section forensic report assembler.

Turns a set of report sections plus the programme files they were computed from
into one Word deliverable with a SHA-256 Basis-of-Analysis appendix — the audit
trail (which files, which hashes, which data dates) a claim submission needs.
Wraps the vendored toolkit assembler; deterministic figures only, LLM narrative
(if any) is analyst-reviewed before it ever reaches here.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.programme_tools.schemas import ArtifactBlob

from .artifacts import persist_blobs

logger = logging.getLogger(__name__)


def _source_files(records: List[Dict[str, Any]]) -> list:
    """XER upload records → SourceFile rows with SHA-256 hashes."""
    from src.programme_tools.vendor.programme.report_docx_assembler import SourceFile

    out = []
    for rec in records or []:
        name = rec.get("file_name") or "programme.xer"
        path = rec.get("file_path") or ""
        sha, count = "", 0
        try:
            data = Path(path).read_bytes()
            sha = hashlib.sha256(data).hexdigest()
        except Exception as e:                                # pragma: no cover
            logger.warning(f"[Export] could not hash {name}: {e}")
        out.append(SourceFile(file_name=name, sha256=sha, data_date=None,
                              role=rec.get("role", "Programme"),
                              activity_count=count))
    return out


def assemble_report(report_title: str, project_name: str,
                    sections: List[Dict[str, Any]],
                    source_records: List[Dict[str, Any]], *,
                    author: str = "COAir",
                    settings: Optional[List[str]] = None,
                    run_id: Optional[str] = None) -> List[dict]:
    """Build a multi-section forensic .docx and persist it. Returns
    ToolResult.artifacts-shaped dicts (helpers.artifact_blocks consumes them).

    sections: [{title, narrative_md?, key_findings?, caveats?}]
    Best-effort: a failure costs the download, not the caller's result.
    """
    try:
        from src.programme_tools.vendor.programme.report_docx_assembler import (
            BasisOfAnalysis, ReportSection, build_assembled_report,
        )
        rsecs = [ReportSection(
            title=s.get("title", ""),
            narrative_md=s.get("narrative_md"),
            key_findings=list(s.get("key_findings") or []),
            caveats=list(s.get("caveats") or [])) for s in sections]
        basis = BasisOfAnalysis(files=_source_files(source_records),
                                settings=list(settings or []))
        data = build_assembled_report(report_title, project_name, author,
                                      rsecs, basis)
        return persist_blobs(
            [ArtifactBlob("programme_report.docx", "docx", data)],
            run_id or uuid.uuid4().hex[:12])
    except Exception as e:
        logger.warning(f"[Export] assembled report failed: {e}")
        return []
