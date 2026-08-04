#!/usr/bin/env python3
"""Idempotently give demo_user an empty, isolated project workspace."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.project_store import get_project_store  # noqa: E402
from src.user_store import get_user_store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default="demo_user")
    parser.add_argument("--name", default="Demo Workspace")
    args = parser.parse_args()
    users = get_user_store(); projects = get_project_store()
    account = users.get_user(args.username)
    if not account or account.get("role") == "admin":
        raise SystemExit("active non-admin demo user is required")
    current = next((project for project in projects.list_for_user(args.username)
                    if project["name"] == args.name), None)
    if current:
        print({"action": "unchanged", "project_id": current["project_id"]})
        return 0
    created = projects.create_project(args.name, args.username)
    print({"action": "created", "project_id": created["project_id"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
