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
INTERFACE_ROOTS = (
    "app.py", "state.py", "views", "test_ui.py",
)


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


def digest_interface() -> tuple[int, str]:
    """Fingerprint the upstream workflow surface independently of engines."""
    paths = []
    for name in INTERFACE_ROOTS:
        path = VENDOR / name
        paths.extend(path.rglob("*.py") if path.is_dir() else [path])
    digest = hashlib.sha256()
    count = 0
    for path in sorted(set(paths)):
        if not path.is_file():
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
    parser.add_argument("--print-interface", action="store_true")
    parser.add_argument("--print-locked-interface", action="store_true")
    args = parser.parse_args()
    count, actual = digest_tree()
    metadata = json.loads(LOCK.read_text(encoding="utf-8"))
    interface_count, interface_actual = digest_interface()
    if args.print_interface:
        print(interface_actual)
        return 0
    if args.print_locked_interface:
        print(metadata.get("interface_sha256", ""))
        return 0
    if args.update:
        metadata["tree_sha256"] = actual
        metadata["interface_sha256"] = interface_actual
        if args.commit:
            metadata["commit"] = args.commit
        from datetime import datetime, timezone
        metadata["synced_at"] = datetime.now(timezone.utc).isoformat()
        LOCK.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        print(f"updated {count} files: {actual}; interface {interface_count}: {interface_actual}")
        return 0
    expected = metadata.get("tree_sha256")
    if expected != actual:
        print(f"vendor integrity mismatch: expected {expected}, got {actual}")
        return 1
    expected_interface = metadata.get("interface_sha256")
    if expected_interface and expected_interface != interface_actual:
        print("vendor interface mismatch: "
              f"expected {expected_interface}, got {interface_actual}")
        return 1
    print(f"vendor integrity OK: {count} files, {actual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
