import sys

from scripts import provision_mobile_smoke_workspace
from src.project_store import ProjectStore
from src.user_store import UserStore


def _run(monkeypatch, users, projects, *, apply=False):
    monkeypatch.setattr(provision_mobile_smoke_workspace, "get_user_store", lambda: users)
    monkeypatch.setattr(provision_mobile_smoke_workspace, "get_project_store", lambda: projects)
    monkeypatch.setenv("MOBILE_SMOKE_PASSWORD", "read-only-secret")
    argv = [
        "provision_mobile_smoke_workspace.py",
        "--owner", "admin2",
        "--password-env", "MOBILE_SMOKE_PASSWORD",
    ]
    if apply:
        argv.append("--apply")
    monkeypatch.setattr(sys, "argv", argv)
    return provision_mobile_smoke_workspace.main()


def test_mobile_smoke_provision_is_dry_run_and_idempotent(monkeypatch, tmp_path):
    users = UserStore(tmp_path / "users.db")
    projects = ProjectStore(tmp_path / "projects.db")
    users.create_user("admin2", "admin123", role="admin")

    assert _run(monkeypatch, users, projects) == 0
    assert users.get_user("mobile_smoke") is None
    assert projects.list_all() == []

    assert _run(monkeypatch, users, projects, apply=True) == 0
    account = users.get_user("mobile_smoke")
    workspace = projects.list_all()[0]
    membership = projects.get_for_user(workspace["project_id"], "mobile_smoke")
    assert account["role"] == "user"
    assert users.verify_password("mobile_smoke", "read-only-secret") is not None
    assert users.billing.summary("mobile_smoke")["credits_total"] == 0
    assert membership["role"] == "viewer"

    assert _run(monkeypatch, users, projects, apply=True) == 0
    assert len(projects.list_all()) == 1
    assert projects.get_for_user(workspace["project_id"], "mobile_smoke")["role"] == "viewer"
