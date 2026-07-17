"""Artifact persistence — the single place bytes become a download URL.

Extracted from programme_tools.executor._persist_artifacts so workflow adapters
(which never run a programme tool) can produce downloads too. It lives in one
module on purpose: ArtifactLinkBlock hard-validates the "/api/artifacts/"
prefix, so a second copy of the URL/filename rules would eventually drift and
start getting blocks silently dropped by the response guard.
"""

from __future__ import annotations

import logging
import re
from typing import List

from src.programme_tools.schemas import ArtifactBlob

logger = logging.getLogger(__name__)

# Filenames are ours, but they are built from titles, so they get sanitized as
# if they were not: this is what keeps "../../etc/passwd" inside the run dir.
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")

_MAX_NAME = 100


def safe_filename(name: str) -> str:
    """Reduce a name to [A-Za-z0-9._-], with no way out of its directory.

    The character class keeps '.', so a name of "." or ".." would survive the
    substitution and still address a directory. Path separators are already
    gone by then, but leading dots are stripped so the result can never be a
    relative path component.
    """
    safe = _SAFE_NAME_RE.sub("_", name or "")[:_MAX_NAME].lstrip(".")
    return safe if safe.strip("._") else "artifact.bin"


def persist_blobs(blobs: List[ArtifactBlob], run_id: str) -> List[dict]:
    """Write bytes under storage/artifacts/<run_id>/ and return artifact dicts
    shaped like ToolResult.artifacts ({artifact_id, kind, filename, url}).

    Raises on disk failure — callers decide whether that costs the download or
    the whole result.
    """
    if not blobs:
        return []
    from src.programme_tools.config_paths import artifacts_dir

    run_dir = artifacts_dir() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    out: List[dict] = []
    for blob in blobs:
        safe = safe_filename(blob.filename)
        (run_dir / safe).write_bytes(blob.data)
        out.append({
            "artifact_id": f"{run_id}/{safe}",
            "kind": blob.kind,
            "filename": safe,
            "url": f"/api/artifacts/{run_id}/{safe}",
        })
    return out
