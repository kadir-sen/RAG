"""Backfill: re-profile existing raw data tables (target_schema=NONE) through
the Excel Schema Profiler.

  confident (schema + no clarify)  → rename parquet columns to canonical +
                                     set header_metadata.target_schema +
                                     persist mapping  (activates deterministic
                                     SQL shortcuts + schema hints)
  clarify   (low coverage)         → tag header_metadata.needs_mapping_review
                                     with best candidate + column_map; leave raw
  none                             → leave raw, untouched

Dry-run by default. Pass --apply to write. --apply backs up catalog.json and
every parquet it rewrites to storage/backup_schema_backfill_<given-stamp>/.

Usage:
  python scripts/backfill_schema_profiler.py                 # dry run
  python scripts/backfill_schema_profiler.py --apply --stamp 20260708_1200
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.catalog import CATALOG_FILE, PARQUET_DIR  # noqa: E402
from src.schema_profiler import get_profiler        # noqa: E402

DATA_TYPES = {"excel", "csv", "parquet", "normalized_raw", "normalized_clean",
              "combined", "unified_schema"}
HELPER_COLS = {"_sheet_name"}

APPLY = "--apply" in sys.argv
STAMP = "manual"
if "--stamp" in sys.argv:
    STAMP = sys.argv[sys.argv.index("--stamp") + 1]
BACKUP_DIR = REPO / "storage" / f"backup_schema_backfill_{STAMP}"


def _parquet_path(table_id: str) -> Path:
    return PARQUET_DIR / f"{table_id}.parquet"


def main() -> None:
    profiler = get_profiler()
    catalog = json.loads(Path(CATALOG_FILE).read_text(encoding="utf-8"))

    confident, clarify, none_, skipped, errors = [], [], [], 0, []

    for entry_key, entry in catalog.items():
        for t in entry.get("tables", []):
            if str(t.get("source_type", "")).lower() not in DATA_TYPES:
                continue
            hm = t.get("header_metadata") or {}
            if hm.get("target_schema"):
                skipped += 1
                continue
            cols = [c for c in (t.get("columns") or []) if c not in HELPER_COLS]
            if not cols:
                none_.append(t["table_id"])
                continue
            try:
                res = profiler.profile(cols)
            except Exception as e:
                errors.append((t["table_id"], str(e)[:120]))
                continue

            if res.schema_id and not res.needs_clarification:
                confident.append((t, res))
            elif res.needs_clarification and res.candidates:
                clarify.append((t, res))
            else:
                none_.append(t["table_id"])

    # ── report ──────────────────────────────────────────────
    print(f"{'APPLY' if APPLY else 'DRY-RUN'}  corpus tables scanned; "
          f"already-canonical skipped={skipped}")
    print(f"  confident={len(confident)}  clarify={len(clarify)}  "
          f"none={len(none_)}  errors={len(errors)}\n")

    print("── CONFIDENT (would assign schema + rename parquet) ──")
    for t, res in confident:
        print(f"  [{res.schema_id} @ {res.confidence:.0%}] {t['table_id']}  "
              f"corpus={t.get('corpus')}")
        print(f"      map: {res.column_map}")
        if res.missing_required:
            print(f"      missing_required: {res.missing_required}")
    print("\n── CLARIFY (would tag needs_mapping_review, leave raw) ──")
    for t, res in clarify:
        print(f"  [{res.candidates[0][0]} @ {res.candidates[0][1]:.0%}] "
              f"{t['table_id']}  corpus={t.get('corpus')}  map={res.column_map}")
    if errors:
        print("\n── ERRORS ──")
        for tid, e in errors:
            print(f"  {tid}: {e}")

    if not APPLY:
        print("\n(dry run — nothing written. Re-run with --apply --stamp <id> to commit.)")
        return

    # ── apply ───────────────────────────────────────────────
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CATALOG_FILE, BACKUP_DIR / "catalog.json")
    applied_conf, applied_clar = 0, 0

    for t, res in confident:
        pq = _parquet_path(t["table_id"])
        if not pq.exists():
            errors.append((t["table_id"], "parquet missing on disk"))
            continue
        shutil.copy2(pq, BACKUP_DIR / pq.name)
        df = pd.read_parquet(pq)
        rename = {raw: canon for raw, canon in res.column_map.items()
                  if raw in df.columns and raw != canon and canon not in df.columns}
        if rename:
            df = df.rename(columns=rename)
            df.to_parquet(pq, index=False)
        t["columns"] = list(df.columns)
        hm = t.setdefault("header_metadata", {})
        hm["target_schema"] = res.schema_id
        hm["schema_backfilled"] = STAMP
        profiler.persist_mapping(
            [c for c in (t.get("columns") or [])], res)
        applied_conf += 1

    for t, res in clarify:
        hm = t.setdefault("header_metadata", {})
        hm["needs_mapping_review"] = True
        hm["mapping_candidate"] = res.candidates[0][0]
        hm["mapping_candidate_confidence"] = round(res.candidates[0][1], 3)
        hm["proposed_column_map"] = res.column_map
        applied_clar += 1

    Path(CATALOG_FILE).write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nAPPLIED: {applied_conf} canonical assignments, "
          f"{applied_clar} clarify tags. Backup → {BACKUP_DIR}")
    print("Reload DuckDB: analyzer.load_from_catalog() (or restart backend).")


if __name__ == "__main__":
    main()
