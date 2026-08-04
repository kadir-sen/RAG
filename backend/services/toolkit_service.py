"""Safe XER persistence outside the document-ingestion pipeline."""
from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from src.billing_store import get_billing_store
from src.config import BASE_DIR
from src.toolkit_store import MAX_ANALYSIS_BYTES, ToolkitStore, get_toolkit_store


class ToolkitProgrammeService:
    def __init__(self, store: ToolkitStore | None = None):
        self.store = store or get_toolkit_store()

    @staticmethod
    def _validate_name(filename: str) -> str:
        safe_name = Path(filename or "").name
        if not safe_name or safe_name != filename or Path(safe_name).suffix.lower() != ".xer":
            raise HTTPException(422, "Only Primavera P6 .xer files are accepted")
        return safe_name

    async def save(self, upload: UploadFile, *, project_id: str, username: str) -> tuple[dict, bool]:
        safe_name = self._validate_name(upload.filename or "")
        target_dir = Path(BASE_DIR) / "data" / "projects" / project_id / "programmes"
        target_dir.mkdir(parents=True, exist_ok=True)
        temp = target_dir / f".{uuid.uuid4().hex}.xer.upload"
        total = 0
        digest = hashlib.sha256()
        has_project = False
        has_task = False
        marker_tail = b""
        try:
            with temp.open("wb") as handle:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_ANALYSIS_BYTES:
                        raise HTTPException(413, "toolkit_analysis_size_exceeded")
                    digest.update(chunk)
                    marker_window = marker_tail + chunk
                    has_project = has_project or b"%T\tPROJECT" in marker_window
                    has_task = has_task or b"%T\tTASK" in marker_window
                    marker_tail = marker_window[-32:]
                    handle.write(chunk)
            if total == 0 or not has_project or not has_task:
                raise HTTPException(422, "invalid_xer_structure")
            sha256 = digest.hexdigest()
            existing = self.store.find_content(project_id, sha256)
            if existing:
                return existing, True
            if self.store.total_bytes(project_id) + total > MAX_ANALYSIS_BYTES:
                raise HTTPException(413, "toolkit_analysis_size_exceeded")

            destination = target_dir / f"{sha256[:12]}-{safe_name}"
            os.replace(temp, destination)
            file_id = f"xer_{sha256[:24]}"
            registered = False
            try:
                get_billing_store().register_storage(
                    username=username, project_id=project_id, file_id=file_id,
                    file_path=str(destination), size_bytes=total,
                )
                registered = True
                result = self.store.add_programme(
                    project_id=project_id, username=username, file_name=safe_name,
                    file_path=str(destination), size_bytes=total, sha256=sha256,
                )
                return result, False
            except Exception:
                if registered:
                    get_billing_store().release_storage(project_id=project_id, file_id=file_id)
                destination.unlink(missing_ok=True)
                raise
        finally:
            temp.unlink(missing_ok=True)

    def delete(self, *, project_id: str, file_id: str) -> bool:
        record = self.store.get_programme(project_id, file_id, include_path=True)
        if not record:
            return False
        try:
            Path(record["file_path"]).unlink(missing_ok=True)
        except OSError as exc:
            raise HTTPException(500, f"programme_delete_failed:{exc}") from exc
        self.store.remove_programme(project_id, file_id)
        get_billing_store().release_storage(project_id=project_id, file_id=file_id)
        return True
