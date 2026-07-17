"""Download endpoint for generated analysis artifacts (xlsx/pdf/docx reports).

Artifacts are written under storage/artifacts/<run_id>/<filename> by
src/export/artifacts.py (used by programme tools and report exports alike);
this router serves them read-only.
Auth is enforced at include_router level (auth_dep in backend/main.py).
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()

_MEDIA_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument."
             "wordprocessingml.document",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".csv": "text/csv",
}


@router.get("/artifacts/{run_id}/{filename}")
def download_artifact(run_id: str, filename: str) -> FileResponse:
    from src.config import ARTIFACTS_DIR

    base = ARTIFACTS_DIR.resolve()
    target = (base / run_id / filename).resolve()
    # Path-traversal guard: the resolved target must stay inside ARTIFACTS_DIR.
    if not target.is_relative_to(base):
        raise HTTPException(status_code=400, detail="Invalid artifact path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    media = _MEDIA_TYPES.get(Path(filename).suffix.lower(),
                             "application/octet-stream")
    return FileResponse(target, media_type=media, filename=filename)
