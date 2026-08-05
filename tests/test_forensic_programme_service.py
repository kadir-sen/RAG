import asyncio
import io
from pathlib import Path

import pytest
from starlette.datastructures import UploadFile

from backend.services.forensic_toolkit.programmes import ForensicProgrammeService
from src.forensic_store import ForensicStore


XER = b"ERMHDR\t19.12\n%T\tPROJECT\n%F\tproj_id\n%R\t1\n%T\tTASK\n%F\ttask_id\n%R\t1\n"


class Billing:
    def __init__(self, fail=False):
        self.fail = fail
        self.registered = []
        self.released = []

    def register_storage(self, **kwargs):
        if self.fail:
            raise RuntimeError("quota")
        self.registered.append(kwargs)

    def release_storage(self, **kwargs):
        self.released.append(kwargs)


def upload(name="programme.xer"):
    return UploadFile(io.BytesIO(XER), filename=name)


def test_concurrent_duplicate_keeps_one_file_and_one_storage_charge(monkeypatch, tmp_path: Path):
    import backend.services.forensic_toolkit.programmes as module
    store = ForensicStore(tmp_path / "forensic.db")
    billing = Billing()
    monkeypatch.setattr(module, "BASE_DIR", tmp_path)
    monkeypatch.setattr(module, "get_billing_store", lambda: billing)
    service = ForensicProgrammeService(store)

    async def save_both():
        return await asyncio.gather(
            service.save(upload(), project_id="p1", username="owner"),
            service.save(upload(), project_id="p1", username="owner"),
        )

    results = asyncio.run(save_both())

    assert sorted(duplicate for _, duplicate in results) == [False, True]
    records = store.list_programmes("p1", include_path=True)
    assert len(records) == 1
    assert Path(records[0]["file_path"]).read_bytes() == XER
    assert len(billing.registered) == 1


def test_failed_quota_registration_removes_file_and_registry_row(monkeypatch, tmp_path: Path):
    import backend.services.forensic_toolkit.programmes as module
    store = ForensicStore(tmp_path / "forensic.db")
    billing = Billing(fail=True)
    monkeypatch.setattr(module, "BASE_DIR", tmp_path)
    monkeypatch.setattr(module, "get_billing_store", lambda: billing)

    with pytest.raises(RuntimeError, match="quota"):
        asyncio.run(ForensicProgrammeService(store).save(
            upload(), project_id="p1", username="owner",
        ))

    assert store.list_programmes("p1") == []
    assert list((tmp_path / "data" / "projects" / "p1" / "programmes").glob("*")) == []
