#!/usr/bin/env python3
"""Idempotently create or update the controlled demo account.

The password is read with ``getpass`` so it is not placed in shell history.
The provider key must already exist as a protected mounted secret; this script
validates it before changing the user or billing account.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.provider_credentials import get_google_api_key_for_ref  # noqa: E402
from src.user_store import UserStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure a controlled COAir demo user.")
    parser.add_argument("--username", default="demo")
    parser.add_argument("--key-ref", default="demo")
    parser.add_argument("--credits", type=float, default=5000.0)
    parser.add_argument("--storage-limit-bytes", type=int, default=30_000_000_000)
    parser.add_argument(
        "--password-env", default="",
        help="Read the password from this environment variable for deployment automation.",
    )
    args = parser.parse_args()

    try:
        # Fail before creating or changing an account if the dedicated secret
        # is unavailable.  This prevents a partially configured demo login.
        get_google_api_key_for_ref(args.key_ref)
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    password = (
        os.getenv(args.password_env, "") if args.password_env
        else getpass.getpass(f"New password for {args.username}: ")
    )
    if len(password) < 8:
        print("error: password must contain at least 8 characters", file=sys.stderr)
        return 2

    store = UserStore()
    record = store.get_user(args.username)
    if record:
        store.update_user(
            args.username,
            display_name=record.get("display_name") or "Demo User",
            role="user",
            token_limit=int(record.get("token_limit") or 1_000_000),
            features=record.get("features") or {},
            password=password,
            is_active=True,
        )
        store.billing.update_account(
            args.username,
            plan_type="demo",
            markup_percent=0,
            storage_limit_bytes=args.storage_limit_bytes,
            model_policy="demo-tiered-quality-v2",
            provider_key_ref=args.key_ref,
        )
    else:
        store.create_user(
            username=args.username,
            password=password,
            display_name="Demo User",
            role="user",
            token_limit=1_000_000,
            features={},
            plan_type="demo",
            initial_credits=args.credits,
            markup_percent=0,
            storage_limit_bytes=args.storage_limit_bytes,
            model_policy="demo-tiered-quality-v2",
            provider_key_ref=args.key_ref,
        )
    summary = store.billing.summary(args.username)
    delta = round(float(args.credits) - float(summary["credits_total"]), 6)
    if delta:
        store.billing.adjust_credits(
            args.username,
            delta,
            "Align dedicated demo account with USD 50 provider budget at provider cost",
            idempotency_key=(
                f"configure-demo:{args.username}:{args.credits}:"
                f"{summary['credits_total']}"
            ),
        )
    result = store.billing.summary(args.username)
    print({
        "username": args.username,
        "role": "user",
        "plan_type": result["plan_type"],
        "credits_total": result["credits_total"],
        "storage_limit_bytes": result["storage_limit_bytes"],
        "dedicated_provider_key": result["dedicated_provider_key"],
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
