import asyncio
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile

import backend.services.toolkit_service as service_module
from backend.services.toolkit_service import ToolkitProgrammeService
from src.toolkit_store import ToolkitStore


VALID_XER = b"ERMHDR\t1\n%T\tPROJECT\n%F\tproj_id\n%R\t1\n%T\tTASK\n%F\ttask_id\n%R\t1\n%E\n"


class FakeBilling:
    def __init__(self):
        self.registered = []
        self.released = []

    def register_storage(self, **kwargs):
        self.registered.append(kwargs)
        return {}

    def release_storage(self, **kwargs):
        self.released.append(kwargs)


def _upload(name: str, content: bytes) -> UploadFile:
    return UploadFile(filename=name, file=BytesIO(content))


def test_xer_upload_is_persistent_deduplicated_and_deletable(tmp_path, monkeypatch):
    store = ToolkitStore(tmp_path / "toolkit.db")
    billing = FakeBilling()
    monkeypatch.setattr(service_module, "BASE_DIR", tmp_path)
    monkeypatch.setattr(service_module, "get_billing_store", lambda: billing)
    service = ToolkitProgrammeService(store)

    record, duplicate = asyncio.run(service.save(
        _upload("baseline.xer", VALID_XER), project_id="project-a", username="alice",
    ))
    assert duplicate is False
    assert len(billing.registered) == 1
    assert store.get_programme("project-a", record["file_id"], include_path=True)

    same, duplicate = asyncio.run(service.save(
        _upload("renamed.xer", VALID_XER), project_id="project-a", username="alice",
    ))
    assert duplicate is True
    assert same["file_id"] == record["file_id"]
    assert len(billing.registered) == 1

    assert service.delete(project_id="project-a", file_id=record["file_id"])
    assert billing.released == [{"project_id": "project-a", "file_id": record["file_id"]}]
    assert store.list_programmes("project-a") == []


def test_xer_upload_rejects_wrong_extension_and_structure(tmp_path, monkeypatch):
    store = ToolkitStore(tmp_path / "toolkit.db")
    monkeypatch.setattr(service_module, "BASE_DIR", tmp_path)
    service = ToolkitProgrammeService(store)

    with pytest.raises(HTTPException) as wrong_extension:
        asyncio.run(service.save(
            _upload("programme.txt", VALID_XER), project_id="project-a", username="alice",
        ))
    assert wrong_extension.value.status_code == 422

    with pytest.raises(HTTPException) as invalid_structure:
        asyncio.run(service.save(
            _upload("programme.xer", b"not an XER"), project_id="project-a", username="alice",
        ))
    assert invalid_structure.value.status_code == 422
    assert not list((tmp_path / "data" / "projects" / "project-a" / "programmes").glob("*"))
