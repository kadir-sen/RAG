#!/usr/bin/env python3
"""Verify or refresh the immutable forensic vendor tree digest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "delay-analysis-toolkit"
LOCK = ROOT / "vendor" / "delay-analysis-toolkit.upstream.json"


def digest_tree() -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    for path in sorted(VENDOR.rglob("*")):
        if (not path.is_file() or "__pycache__" in path.parts or ".pytest_cache" in path.parts
                or path.suffix in {".pyc", ".pyo"}):
            continue
        relative = path.relative_to(VENDOR).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
        count += 1
    return count, digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--commit", default="")
    args = parser.parse_args()
    count, actual = digest_tree()
    metadata = json.loads(LOCK.read_text(encoding="utf-8"))
    if args.update:
        metadata["tree_sha256"] = actual
        if args.commit:
            metadata["commit"] = args.commit
        from datetime import datetime, timezone
        metadata["synced_at"] = datetime.now(timezone.utc).isoformat()
        LOCK.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        print(f"updated {count} files: {actual}")
        return 0
    expected = metadata.get("tree_sha256")
    if expected != actual:
        print(f"vendor integrity mismatch: expected {expected}, got {actual}")
        return 1
    print(f"vendor integrity OK: {count} files, {actual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
