import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.project_store import ProjectStore


def test_project_membership_is_the_visibility_boundary(tmp_path):
    store = ProjectStore(tmp_path / "projects.db")
    alpha = store.create_project("Alpha Matter", "alice")
    beta = store.create_project("Beta Matter", "bob", embedding_profile="gemini-embedding-2")

    assert store.get_for_user(alpha["project_id"], "alice")["role"] == "owner"
    assert store.get_for_user(alpha["project_id"], "bob") is None
    assert [p["project_id"] for p in store.list_for_user("alice")] == [alpha["project_id"]]

    store.add_member(beta["project_id"], "alice", "viewer")
    assert store.get_for_user(beta["project_id"], "alice")["role"] == "viewer"
    assert {p["project_id"] for p in store.list_for_user("alice")} == {
        alpha["project_id"], beta["project_id"],
    }

    assert store.archive(alpha["project_id"])
    assert [p["project_id"] for p in store.list_for_user("alice")] == [beta["project_id"]]


def test_embedding_profile_is_fixed_when_project_is_created(tmp_path):
    store = ProjectStore(tmp_path / "projects.db")
    project = store.create_project("Local corpus", "owner")
    assert project["embedding_profile"] == "local-bge-v1"


def test_project_vector_lifecycle_is_durable(tmp_path):
    store = ProjectStore(tmp_path / "projects.db")
    project = store.create_project("Vector matter", "owner")
    project_id = project["project_id"]

    assert store.get_vector_state(project_id)["status"] == "empty"
    store.set_vector_state(project_id, "provisioning")
    store.set_vector_state(project_id, "indexing", point_count=0)
    ready = store.set_vector_state(project_id, "ready", point_count=42)

    assert ready["point_count"] == 42
    assert ready["provisioned_at"]
    assert ready["collection_name"]

    assert store.archive(project_id)
    assert store.get_vector_state(project_id)["status"] == "archived"
