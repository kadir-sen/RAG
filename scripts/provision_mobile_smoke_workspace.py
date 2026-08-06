#!/usr/bin/env python3
"""Provision the isolated, read-only production UI smoke identity.

The command is dry-run by default. It never uploads, deletes or rewrites
project documents; an administrator adds the harmless PDF/XLSX fixtures once
and then stores the printed project ID in PROD_E2E_PROJECT_ID.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.project_store import get_project_store  # noqa: E402
from src.user_store import get_user_store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision the read-only mobile smoke workspace.")
    parser.add_argument("--username", default="mobile_smoke")
    parser.add_argument("--display", default="Mobile UI Smoke")
    parser.add_argument("--owner", default="admin2", help="Existing admin that owns the fixture project.")
    parser.add_argument("--project-name", default="Mobile Smoke Workspace")
    parser.add_argument("--password-env", default="PROD_E2E_PASSWORD")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    password = os.getenv(args.password_env, "")
    if not password:
        print(f"error: {args.password_env} must contain the smoke password", file=sys.stderr)
        return 2

    users = get_user_store()
    projects = get_project_store()
    owner = users.get_user(args.owner)
    if not owner or owner.get("role") != "admin" or not owner.get("is_active"):
        print("error: an active admin owner is required", file=sys.stderr)
        return 2

    existing_user = users.get_user(args.username)
    existing_project = next(
        (project for project in projects.list_all() if project["name"] == args.project_name),
        None,
    )
    preview = {
        "action": "apply" if args.apply else "dry-run",
        "username": args.username,
        "user_action": "update" if existing_user else "create",
        "project_action": "reuse" if existing_project else "create",
        "project_id": existing_project["project_id"] if existing_project else None,
        "membership": "viewer",
        "fixture_requirement": "one harmless PDF and one harmless XLSX/CSV",
    }
    if not args.apply:
        print(json.dumps(preview, sort_keys=True))
        return 0

    if existing_user:
        users.update_user(
            args.username,
            display_name=args.display,
            role="user",
            token_limit=0,
            features={},
            is_active=True,
            password=password,
        )
    else:
        users.create_user(
            args.username,
            password,
            display_name=args.display,
            role="user",
            token_limit=0,
            features={},
            plan_type="demo",
            initial_credits=0,
            markup_percent=0,
            storage_limit_bytes=0,
            model_policy="demo-tiered-quality-v2",
        )

    project = existing_project or projects.create_project(args.project_name, args.owner)
    projects.add_member(project["project_id"], args.username, "viewer")
    preview.update({"project_id": project["project_id"], "configured": True})
    print(json.dumps(preview, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
