#!/usr/bin/env python3
"""List or remove legacy chronology LLM response-cache records.

Dry-run is the default.  OCR, embeddings and unrelated chat entries are never
selected by this command.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.llm_client import cache_keys, delete_cache_key  # noqa: E402


PREFIXES = ("chronology-report:", "chron-plan:", "chronology:", "chronology-")


def selected_keys() -> list[str]:
    return sorted(key for key in cache_keys() if key.startswith(PREFIXES))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="delete selected records")
    args = parser.parse_args()
    keys = selected_keys()
    removed = sum(1 for key in keys if args.apply and delete_cache_key(key))
    action = "removed" if args.apply else "would_remove"
    print({"action": action, "matched": len(keys), "removed": removed})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
