"""Clear local caches and persisted registries used by the COAir backend.

Targets:
  - cache/cache.db                       (SQLite RAG embedding cache)
  - storage/document_registry.json       (persistent document library)
  - storage/parquet/catalog.json         (Excel/CSV table catalog)
  - .cache/                              (third-party caches, OCR cache, etc.)

Run:
    python scripts/clear_caches.py            # interactive prompt
    python scripts/clear_caches.py --yes      # no prompt
    python scripts/clear_caches.py --only registry,catalog
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TARGETS = {
    "rag_cache": ROOT / "cache" / "cache.db",
    "registry": ROOT / "storage" / "document_registry.json",
    "catalog": ROOT / "storage" / "parquet" / "catalog.json",
    "parquet_files": ROOT / "storage" / "parquet",  # directory, kept but parquet wiped
    "dotcache": ROOT / ".cache",
}


def _describe(path: Path) -> str:
    if not path.exists():
        return f"(missing) {path}"
    if path.is_file():
        size_kb = path.stat().st_size // 1024
        return f"file {size_kb} KB — {path}"
    return f"dir — {path}"


def _delete(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        if path.is_file():
            path.unlink()
        else:
            shutil.rmtree(path)
        return True
    except Exception as e:
        print(f"  ! could not delete {path}: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true",
                        help="Skip confirmation prompt")
    parser.add_argument("--only", default="",
                        help=("Comma-separated subset of: "
                              f"{', '.join(TARGETS.keys())}"))
    args = parser.parse_args()

    if args.only:
        wanted = {t.strip() for t in args.only.split(",") if t.strip()}
        unknown = wanted - TARGETS.keys()
        if unknown:
            print(f"Unknown targets: {sorted(unknown)}", file=sys.stderr)
            return 2
        plan = {k: v for k, v in TARGETS.items() if k in wanted}
    else:
        plan = dict(TARGETS)

    print("The following cache targets will be removed:")
    for key, path in plan.items():
        print(f"  [{key}] {_describe(path)}")

    if not args.yes:
        answer = input("\nProceed? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return 1

    removed = 0
    for key, path in plan.items():
        # For parquet_files we wipe contents but preserve the directory so the
        # backend can write new entries without re-creating the path.
        if key == "parquet_files" and path.exists() and path.is_dir():
            for child in path.iterdir():
                if _delete(child):
                    removed += 1
            print(f"  - cleared contents of {path}")
            continue
        if _delete(path):
            removed += 1
            print(f"  - removed {path}")

    print(f"\nDone. {removed} item(s) removed.")
    print("Restart the backend to re-hydrate from remote storage (if any).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
