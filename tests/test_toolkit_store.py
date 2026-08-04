from pathlib import Path

import pytest

from src.toolkit_store import MAX_ANALYSIS_BYTES, ToolkitStore


def _store(tmp_path: Path) -> ToolkitStore:
    return ToolkitStore(tmp_path / "toolkit.db")


def test_programme_inventory_deduplicates_content_and_releases_on_delete(tmp_path):
    store = _store(tmp_path)
    first = store.add_programme(
        project_id="project-a", username="alice", file_name="baseline.xer",
        file_path="/data/baseline.xer", size_bytes=120, sha256="a" * 64,
    )
    duplicate = store.add_programme(
        project_id="project-a", username="alice", file_name="renamed.xer",
        file_path="/data/renamed.xer", size_bytes=120, sha256="a" * 64,
    )
    assert duplicate == first
    assert store.total_bytes("project-a") == 120
    assert len(store.list_programmes("project-a")) == 1

    removed = store.remove_programme("project-a", first["file_id"])
    assert removed is not None
    assert store.total_bytes("project-a") == 0
    assert store.list_programmes("project-a") == []


def test_programme_inventory_enforces_aggregate_analysis_budget(tmp_path):
    store = _store(tmp_path)
    store.add_programme(
        project_id="project-a", username="alice", file_name="one.xer",
        file_path="/data/one.xer", size_bytes=MAX_ANALYSIS_BYTES - 10,
        sha256="a" * 64,
    )
    with pytest.raises(ValueError, match="toolkit_analysis_size_exceeded"):
        store.add_programme(
            project_id="project-a", username="alice", file_name="two.xer",
            file_path="/data/two.xer", size_bytes=11, sha256="b" * 64,
        )


def test_launch_ticket_is_project_scoped_single_use_and_creates_session(tmp_path):
    store = _store(tmp_path)
    ticket = store.create_ticket(
        username="alice", project_id="project-a", project_role="editor",
    )
    session = store.consume_ticket(ticket)
    assert session is not None
    assert session["username"] == "alice"
    assert session["project_id"] == "project-a"
    assert session["project_role"] == "editor"
    assert store.consume_ticket(ticket) is None

    validated = store.validate_session(session["session_token"])
    assert validated is not None
    assert validated["project_id"] == "project-a"
    assert store.validate_session("wrong-token") is None


def test_expired_launch_ticket_is_rejected(tmp_path):
    store = _store(tmp_path)
    ticket = store.create_ticket(
        username="alice", project_id="project-a", project_role="owner",
    )
    with store._connect() as conn:
        conn.execute("UPDATE toolkit_sessions SET expires_at=0")
    assert store.consume_ticket(ticket) is None
