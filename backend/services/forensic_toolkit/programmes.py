"""Validated XER persistence that deliberately bypasses RAG ingestion."""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from src.billing_store import get_billing_store
from src.config import BASE_DIR
from src.forensic_store import MAX_WORKSPACE_BYTES, ForensicStore, get_forensic_store


class ForensicProgrammeService:
    def __init__(self, store: ForensicStore | None = None):
        self.store = store or get_forensic_store()

    @staticmethod
    def validate_name(filename: str) -> str:
        safe_name = Path(filename or "").name
        if (not safe_name or safe_name != filename
                or Path(safe_name).suffix.casefold() != ".xer"):
            raise HTTPException(422, "Only Primavera P6 .xer files are accepted")
        return safe_name

    async def save(self, upload: UploadFile, *, project_id: str,
                   username: str) -> tuple[dict, bool]:
        safe_name = self.validate_name(upload.filename or "")
        target_dir = Path(BASE_DIR) / "data" / "projects" / project_id / "programmes"
        target_dir.mkdir(parents=True, exist_ok=True)
        temporary = target_dir / f".{uuid.uuid4().hex}.xer.upload"
        digest = hashlib.sha256()
        total = 0
        marker_tail = b""
        has_project = False
        has_task = False
        try:
            with temporary.open("wb") as target:
                while chunk := await upload.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_WORKSPACE_BYTES:
                        raise HTTPException(413, "forensic_programme_size_exceeded")
                    digest.update(chunk)
                    marker = marker_tail + chunk
                    has_project = has_project or b"%T\tPROJECT" in marker
                    has_task = has_task or b"%T\tTASK" in marker
                    marker_tail = marker[-64:]
                    target.write(chunk)
            if not total or not has_project or not has_task:
                raise HTTPException(422, "invalid_xer_structure")

            sha256 = digest.hexdigest()
            existing = self.store.find_content(project_id, sha256)
            if existing:
                return existing, True

            # A unique staging destination prevents two simultaneous uploads of
            # identical content from unlinking the winner's file when the
            # database uniqueness check identifies the second as a duplicate.
            destination = target_dir / f"{sha256[:16]}-{uuid.uuid4().hex[:8]}-{safe_name}"
            os.replace(temporary, destination)
            record: dict | None = None
            try:
                record, duplicate = self.store.add_programme(
                    project_id=project_id, username=username, file_name=safe_name,
                    file_path=str(destination), size_bytes=total, sha256=sha256,
                )
                if duplicate:
                    destination.unlink(missing_ok=True)
                    return record, True
                get_billing_store().register_storage(
                    username=username, project_id=project_id,
                    file_id=record["file_id"], file_path=str(destination),
                    size_bytes=total,
                )
                return record, False
            except Exception:
                if record:
                    self.store.remove_programme(project_id, record["file_id"])
                    get_billing_store().release_storage(
                        project_id=project_id, file_id=record["file_id"],
                    )
                destination.unlink(missing_ok=True)
                raise
        finally:
            temporary.unlink(missing_ok=True)

    def delete(self, *, project_id: str, file_id: str) -> bool:
        record = self.store.get_programme(project_id, file_id, include_path=True)
        if not record:
            return False
        Path(record["file_path"]).unlink(missing_ok=True)
        self.store.remove_programme(project_id, file_id)
        get_billing_store().release_storage(project_id=project_id, file_id=file_id)
        return True
