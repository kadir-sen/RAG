#!/usr/bin/env python3
"""Idempotently import historical LLM calls and source-file ownership.

Dry-run is the default. Use ``--apply`` after taking the normal storage backup.
Historical events are report-only and never debit a user's current credits.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.billing_store import get_billing_store  # noqa: E402
from src.config import STORAGE_DIR  # noqa: E402
from src.document_registry import get_document_registry  # noqa: E402
from src.project_store import get_project_store  # noqa: E402
from src.user_store import get_user_store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    runs_db = Path(STORAGE_DIR) / "query_runs.db"
    calls = []
    if runs_db.exists():
        conn = sqlite3.connect(runs_db); conn.row_factory = sqlite3.Row
        calls = conn.execute(
            "SELECT l.*,r.username,r.project_id FROM llm_calls l "
            "JOIN query_runs r ON r.run_id=l.run_id"
        ).fetchall()
        conn.close()
    records = [r for r in get_document_registry().get_all() if r.project_id]
    print(f"historical LLM calls: {len(calls)}")
    print(f"project source records: {len(records)}")
    if not args.apply:
        print("dry-run only; pass --apply to write")
        return 0

    users = get_user_store(); billing = get_billing_store()

    imported = 0
    for row in calls:
        if not row["username"] or not users.get_user(row["username"]):
            continue
        nanos = int((Decimal(str(row["cost_usd"] or 0)) * Decimal(1_000_000_000)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        ))
        billing.record_charge(
            username=row["username"], project_id=row["project_id"] or "",
            run_id=row["run_id"] or "", task_type="historical",
            provider=row["provider"] or "", model=row["model"] or "",
            prompt_tokens=row["prompt_tokens"] or 0,
            completion_tokens=row["completion_tokens"] or 0,
            reasoning_tokens=row["reasoning_tokens"] or 0,
            cached_tokens=row["cached_tokens"] or 0,
            provider_cost_nanos=nanos, usage_source="historical",
            pricing_version="legacy-estimate",
            idempotency_key=f"historical:{row['call_id']}",
            event_type="historical", debit=False,
        )
        imported += 1

    owned = 0
    projects = get_project_store()
    for record in records:
        project = projects.get(record.project_id)
        owner = str((project or {}).get("created_by") or "")
        if not owner or not users.get_user(owner):
            continue
        path = Path(record.file_path)
        size = path.stat().st_size if path.is_file() else int(record.file_size_kb or 0) * 1024
        billing.register_storage(
            username=owner, project_id=record.project_id, file_id=record.doc_id,
            file_path=record.file_path, size_bytes=size,
        )
        owned += 1
    print(f"imported {imported} historical calls and {owned} source objects")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
