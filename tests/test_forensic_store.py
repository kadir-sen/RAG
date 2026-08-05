from pathlib import Path

import pytest

from src.forensic_store import ForensicStore, MAX_WORKSPACE_BYTES
from backend.services.forensic_toolkit.sources import ForensicSourceService


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


def test_workspace_state_is_optimistic_and_does_not_mutate_source_revision(tmp_path: Path):
    store = ForensicStore(tmp_path / "forensic.db")
    programme = _programme(store, tmp_path, "p1", "a")
    workspace = store.create_workspace(
        project_id="p1", username="owner", name="Analysis",
        programme_ids=[programme["file_id"]], settings={},
    )
    before = workspace["source_revision"]
    updated = store.update_workspace_state(
        project_id="p1", workspace_id=workspace["workspace_id"], expected_version=1,
        patch={"contract_completion_milestone": "MS1000"},
    )
    assert updated["version"] == 2
    assert updated["state"]["contract_completion_milestone"] == "MS1000"
    assert store.get_workspace("p1", workspace["workspace_id"])["source_revision"] == before
    with pytest.raises(ValueError, match="version_conflict"):
        store.update_workspace_state(
            project_id="p1", workspace_id=workspace["workspace_id"],
            expected_version=1, patch={"missing_inputs": ["logic narrative"]},
        )
    run = store.enqueue_run(
        project_id="p1", workspace_id=workspace["workspace_id"], username="owner",
        module_slug="dcma", parameters={},
    )
    assert run["parameters"]["_state_version"] == 2


def test_selected_source_snapshot_survives_original_deletion(tmp_path: Path, monkeypatch):
    import backend.services.forensic_toolkit.sources as source_module

    monkeypatch.setattr(source_module, "STORAGE_DIR", tmp_path / "storage")
    store = ForensicStore(tmp_path / "forensic.db")
    programme = _programme(store, tmp_path, "p1", "a")
    workspace = store.create_workspace(
        project_id="p1", username="owner", name="Analysis",
        programme_ids=[programme["file_id"]], settings={},
    )
    service = ForensicSourceService(store)
    resolved = service.resolve_selection(
        project_id="p1", workspace_id=workspace["workspace_id"],
        selections=[{"source_id": programme["file_id"], "selected_scope": {}}],
    )
    selected = store.replace_workspace_sources(
        project_id="p1", workspace_id=workspace["workspace_id"],
        expected_version=1, sources=resolved,
    )
    assert selected["version"] == 2
    (tmp_path / "a.xer").unlink()
    pinned = store.resolve_workspace_programmes("p1", workspace["workspace_id"])
    assert Path(pinned[0]["file_path"]).is_file()
    assert pinned[0]["sha256"] == resolved[0]["content_hash"]


def test_evidence_documents_keep_spreadsheet_row_anchors(tmp_path: Path):
    store = ForensicStore(tmp_path / "forensic.db")
    programme = _programme(store, tmp_path, "p1", "a")
    workspace = store.create_workspace(
        project_id="p1", username="owner", name="Analysis",
        programme_ids=[programme["file_id"]], settings={},
    )
    csv_path = tmp_path / "events.csv"
    csv_path.write_text("Date,Event\n2026-01-01,Access granted\n2026-01-02,Work starts\n")
    selected = [
        {"source_id": programme["file_id"], "source_kind": "programme",
         "file_name": "a.xer", "extension": ".xer", "size_bytes": 10,
         "content_hash": "a" * 64, "status": "ready", "capabilities": [],
         "selected_scope": {}, "snapshot_path": str(tmp_path / "a.xer")},
        {"source_id": "doc-events", "source_kind": "data",
         "file_name": "events.csv", "extension": ".csv",
         "size_bytes": csv_path.stat().st_size, "content_hash": "b" * 64,
         "status": "ready", "capabilities": ["table_rows"],
         "selected_scope": {"row_from": 2, "row_to": 3},
         "snapshot_path": str(csv_path)},
    ]
    store.replace_workspace_sources(
        project_id="p1", workspace_id=workspace["workspace_id"],
        expected_version=1, sources=selected,
    )
    documents = ForensicSourceService(store).evidence_documents(
        project_id="p1", workspace_id=workspace["workspace_id"],
        source_ids=["doc-events"],
    )
    assert documents[0][0] == "events.csv"
    assert "<!-- row:2 --> 2026-01-01 | Access granted" in documents[0][1]
    assert "<!-- row:1 -->" not in documents[0][1]
