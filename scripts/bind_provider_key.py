#!/usr/bin/env python3
"""Bind an existing user to a mounted provider-key alias.

This command deliberately has no ``--key`` argument. Secret material must be
installed in the server's protected secret directory outside Git and the
container image before this command is run.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.provider_credentials import get_google_api_key_for_ref  # noqa: E402
from src.user_store import UserStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Bind a COAir user to a key alias.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--key-ref", required=True)
    args = parser.parse_args()

    store = UserStore()
    if not store.get_user(args.username):
        print("error: user_not_found", file=sys.stderr)
        return 2
    try:
        # Validate file, permissions and content before changing the account.
        get_google_api_key_for_ref(args.key_ref)
        store.billing.update_account(
            args.username, provider_key_ref=args.key_ref,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"bound {args.username!r} to provider key alias {args.key_ref!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
