from pathlib import Path

import pytest

from src.forensic_store import ForensicStore, MAX_WORKSPACE_BYTES


def _programme(store: ForensicStore, root: Path, project: str, suffix: str, size: int = 10):
    path = root / f"{suffix}.xer"
    path.write_text("ERMHDR\n%T\tPROJECT\n%T\tTASK\n", encoding="utf-8")
    record, duplicate = store.add_programme(
        project_id=project, username="owner", file_name=path.name,
        file_path=str(path), size_bytes=size, sha256=(suffix * 64)[:64],
    )
    assert not duplicate
    return record


def test_programme_duplicate_workspace_and_project_isolation(tmp_path: Path):
    store = ForensicStore(tmp_path / "forensic.db")
    first = _programme(store, tmp_path, "p1", "a")
    duplicate, is_duplicate = store.add_programme(
        project_id="p1", username="owner", file_name="copy.xer",
        file_path="/unused", size_bytes=10, sha256="a" * 64,
    )
    assert is_duplicate and duplicate["file_id"] == first["file_id"]
    assert store.get_programme("p2", first["file_id"]) is None

    workspace = store.create_workspace(
        project_id="p1", username="owner", name="Analysis",
        programme_ids=[first["file_id"]], settings={"completion": "MS1000"},
    )
    assert workspace["source_revision"]
    assert store.get_workspace("p2", workspace["workspace_id"]) is None

    run = store.enqueue_run(
        project_id="p1", workspace_id=workspace["workspace_id"], username="owner",
        module_slug="dcma", parameters={"programme_index": -1},
    )
    assert run["status"] == "queued"
    assert store.get_run("p2", run["run_id"]) is None
    assert store.claim_next_run()["run_id"] == run["run_id"]
    store.complete_run(run["run_id"], {"metrics": []})
    assert store.get_run("p1", run["run_id"])["status"] == "ready"


def test_workspace_enforces_75_mib_selected_source_limit(tmp_path: Path):
    store = ForensicStore(tmp_path / "forensic.db")
    first = _programme(store, tmp_path, "p1", "a", MAX_WORKSPACE_BYTES)
    second = _programme(store, tmp_path, "p1", "b", 1)
    with pytest.raises(ValueError, match="forensic_workspace_size_exceeded"):
        store.create_workspace(
            project_id="p1", username="owner", name="Too large",
            programme_ids=[first["file_id"], second["file_id"]], settings={},
        )


def test_failed_run_retries_with_same_identity_and_sources(tmp_path: Path):
    store = ForensicStore(tmp_path / "forensic.db")
    programme = _programme(store, tmp_path, "p1", "a")
    workspace = store.create_workspace(
        project_id="p1", username="owner", name="Analysis",
        programme_ids=[programme["file_id"]], settings={},
    )
    run = store.enqueue_run(
        project_id="p1", workspace_id=workspace["workspace_id"], username="owner",
        module_slug="dcma", parameters={},
    )
    store.fail_run(run["run_id"], error_code="forensic_engine_failed", traceback_id="ftb_test")
    retried = store.retry_run("p1", run["run_id"])
    assert retried is not None
    assert retried["run_id"] == run["run_id"]
    assert retried["source_revision"] == run["source_revision"]
    assert retried["attempt"] == 2
    assert retried["status"] == "queued"
