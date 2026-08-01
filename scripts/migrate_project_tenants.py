"""Audit and prepare the shared Qdrant collection for project multitenancy.

Dry-run is the default. ``--apply`` creates a collection snapshot and the
required payload indexes without changing or deleting any point. Orphan points
remain quarantined because all application reads require project_id.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _count(client, collection: str, flt=None) -> int:
    return int(client.count(collection, count_filter=flt, exact=True).count or 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--enable-strict", action="store_true")
    parser.add_argument("--expected-total", type=int)
    parser.add_argument("--expected-assigned", type=int)
    parser.add_argument("--expected-orphans", type=int)
    args = parser.parse_args()

    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels
    from src.config import QDRANT_API_KEY, QDRANT_COLLECTION, QDRANT_URL, STORAGE_DIR
    from src.project_store import get_project_store

    client = QdrantClient(
        url=QDRANT_URL, api_key=QDRANT_API_KEY or None, timeout=120,
        check_compatibility=False,
    )
    has_project = qmodels.Filter(must_not=[
        qmodels.IsEmptyCondition(is_empty=qmodels.PayloadField(key="project_id")),
    ])
    orphan_filter = qmodels.Filter(must=[
        qmodels.IsEmptyCondition(is_empty=qmodels.PayloadField(key="project_id")),
    ])
    total = _count(client, QDRANT_COLLECTION)
    assigned = _count(client, QDRANT_COLLECTION, has_project)
    orphans = _count(client, QDRANT_COLLECTION, orphan_filter)
    expected = {
        "total": args.expected_total,
        "assigned": args.expected_assigned,
        "orphans": args.expected_orphans,
    }
    actual = {"total": total, "assigned": assigned, "orphans": orphans}
    mismatches = {
        key: {"expected": value, "actual": actual[key]}
        for key, value in expected.items()
        if value is not None and value != actual[key]
    }
    if total != assigned + orphans:
        mismatches["partition_sum"] = {
            "expected": total, "actual": assigned + orphans,
        }

    orphan_points, _ = client.scroll(
        QDRANT_COLLECTION, scroll_filter=orphan_filter, limit=max(1, orphans),
        with_payload=True, with_vectors=False,
    )
    projects = []
    for project in get_project_store().list_all(include_archived=True):
        pid = project["project_id"]
        flt = qmodels.Filter(must=[qmodels.FieldCondition(
            key="project_id", match=qmodels.MatchValue(value=pid),
        )])
        projects.append({
            "project_id": pid,
            "name": project["name"],
            "archived_at": project.get("archived_at"),
            "points": _count(client, QDRANT_COLLECTION, flt),
        })

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(STORAGE_DIR) / "migrations" / "project-tenants"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / f"manifest-{stamp}.json"
    manifest = {
        "created_at": stamp,
        "collection": QDRANT_COLLECTION,
        "counts": actual,
        "projects": projects,
        "quarantine": [
            {"point_id": str(p.id), "payload": p.payload or {}}
            for p in orphan_points
        ],
        "mismatches": mismatches,
        "applied": False,
        "snapshot": None,
        "strict_mode": False,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path), **actual, "mismatches": mismatches}, indent=2))
    if mismatches:
        print("Refusing migration because counts do not match.", file=sys.stderr)
        return 2
    if not args.apply:
        print("Dry-run complete; no Qdrant changes were made.")
        return 0

    snapshot = client.create_snapshot(QDRANT_COLLECTION, wait=True)
    manifest["snapshot"] = getattr(snapshot, "name", None)

    info = client.get_collection(QDRANT_COLLECTION)
    schema = getattr(info, "payload_schema", {}) or {}
    if "project_id" not in schema:
        client.create_payload_index(
            QDRANT_COLLECTION, "project_id",
            qmodels.KeywordIndexParams(
                type=qmodels.KeywordIndexType.KEYWORD, is_tenant=True,
            ),
            wait=True,
        )
    for field in (
        "file_id", "doc_id", "file_name", "corpus", "doc_type",
        "project", "reference", "date",
    ):
        if field not in schema:
            client.create_payload_index(
                QDRANT_COLLECTION, field, qmodels.PayloadSchemaType.KEYWORD,
                wait=True,
            )

    after = {
        "total": _count(client, QDRANT_COLLECTION),
        "assigned": _count(client, QDRANT_COLLECTION, has_project),
        "orphans": _count(client, QDRANT_COLLECTION, orphan_filter),
    }
    if after != actual:
        raise RuntimeError(f"point counts changed during index creation: {actual} -> {after}")
    if args.enable_strict:
        client.update_collection(
            QDRANT_COLLECTION,
            strict_mode_config=qmodels.StrictModeConfig(
                enabled=True,
                unindexed_filtering_retrieve=False,
                unindexed_filtering_update=False,
            ),
        )
        manifest["strict_mode"] = True
    manifest["applied"] = True
    manifest["after_counts"] = after
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"applied": True, "snapshot": manifest["snapshot"], "counts": after}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
