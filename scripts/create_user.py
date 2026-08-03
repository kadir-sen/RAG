#!/usr/bin/env python3
"""
Admin-only user provisioning CLI.

Usage:
    python scripts/create_user.py \\
        --username acme --password 'change-me' \\
        --display 'Acme Corp' --token-limit 2000000 \\
        --features correspondence,provider_compare \\
        --role user

To bootstrap an admin account:
    python scripts/create_user.py --username admin --password 'admin-pw' --role admin
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root on sys.path so `src.*` imports work when invoked directly.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.user_store import UserStore  # noqa: E402


def _parse_features(raw: str) -> dict:
    flags: dict = {}
    if not raw:
        return flags
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            key, val = part.split("=", 1)
            flags[key.strip()] = val.strip().lower() in {"1", "true", "yes", "on"}
        else:
            flags[part] = True
    return flags


def main() -> int:
    ap = argparse.ArgumentParser(description="Create or update a COAir user.")
    ap.add_argument("--username", required=True)
    ap.add_argument("--password", default="")
    ap.add_argument("--display", default=None, help="Display name (defaults to username).")
    ap.add_argument("--role", default="user", choices=["user", "admin"])
    ap.add_argument(
        "--token-limit",
        type=int,
        default=1_000_000,
        help="Total hard cap (prompt+completion tokens combined).",
    )
    ap.add_argument("--plan", default="demo", choices=["demo", "legacy"])
    ap.add_argument("--initial-credits", type=float, default=1000.0)
    ap.add_argument("--markup-percent", type=float, default=30.0)
    ap.add_argument("--storage-limit-bytes", type=int, default=30_000_000_000)
    ap.add_argument("--model-policy", default="demo-gemini-3.6-v1")
    ap.add_argument("--add-credits", type=float, default=0.0,
                    help="Append a signed credit adjustment to an existing account.")
    ap.add_argument("--reason", default="", help="Required with --add-credits.")
    ap.add_argument(
        "--features",
        default="",
        help="Comma-separated feature flags, e.g. 'correspondence,provider_compare' "
        "or 'correspondence=true,provider_compare=false'.",
    )
    ap.add_argument(
        "--update",
        action="store_true",
        help="If the user exists, update fields instead of failing.",
    )
    args = ap.parse_args()

    store = UserStore()
    features = _parse_features(args.features)
    existing = store.get_user(args.username)
    if args.add_credits:
        if not existing:
            print(f"error: user {args.username!r} does not exist", file=sys.stderr)
            return 2
        if not args.reason.strip():
            print("error: --reason is required with --add-credits", file=sys.stderr)
            return 2
        print(store.billing.adjust_credits(args.username, args.add_credits, args.reason))
        return 0
    if not args.password:
        print("error: --password is required when creating/updating a user", file=sys.stderr)
        return 2
    if existing and not args.update:
        print(
            f"error: user {args.username!r} already exists. "
            f"Re-run with --update to overwrite fields.",
            file=sys.stderr,
        )
        return 2

    if existing:
        record = store.update_user(
            args.username,
            display_name=args.display or existing.get("display_name") or args.username,
            role=args.role,
            token_limit=args.token_limit,
            features=features,
            password=args.password,
        )
        print(f"updated {args.username}: {record}")
    else:
        record = store.create_user(
            username=args.username,
            password=args.password,
            display_name=args.display or args.username,
            role=args.role,
            token_limit=args.token_limit,
            features=features,
            plan_type="legacy" if args.role == "admin" else args.plan,
            initial_credits=0 if args.role == "admin" else args.initial_credits,
            markup_percent=args.markup_percent,
            storage_limit_bytes=0 if args.role == "admin" else args.storage_limit_bytes,
            model_policy="" if args.role == "admin" else args.model_policy,
        )
        print(f"created {args.username}: {record}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
