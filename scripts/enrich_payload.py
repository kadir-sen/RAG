"""Scoped-metadata payload pass: stamp filterable fields onto Qdrant vectors.

Reads the corpus manifest and writes per-document metadata (project, doc_type,
date, reference, title) into the payload of that document's vectors via Qdrant
set_payload — NO re-embedding. This powers scoped retrieval ("documents about
project X", "only witness statements", date ranges) and mitigates vector-search
dilution as the corpus grows.

LLM-free and idempotent (set_payload merges keys), so it is safe to re-run after
more documents are ingested.

Run (against the local Qdrant the ingest writes to):
    QDRANT_URL=http://localhost:6333 QDRANT_COLLECTION=coair \
    PYTHONPATH=. python scripts/enrich_payload.py \
        --manifest data/edinburgh_tram/manifest.csv --project "Edinburgh Tram Inquiry"
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(ROOT / "data" / "edinburgh_tram" / "manifest.csv"))
    parser.add_argument("--project", default="Edinburgh Tram Inquiry")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--collection", default=os.getenv("QDRANT_COLLECTION", "coair"))
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"))
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels

    client = QdrantClient(url=args.qdrant_url, timeout=60.0, check_compatibility=False)

    # Index file_name FIRST so the per-document set_payload filter is a fast index
    # lookup instead of a full collection scan (huge speedup on large collections).
    try:
        client.create_payload_index(
            collection_name=args.collection, field_name="file_name",
            field_schema=qmodels.PayloadSchemaType.KEYWORD)
        print("file_name payload index ensured")
    except Exception:
        pass  # already exists

    with open(args.manifest, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if args.limit:
        rows = rows[: args.limit]

    updated = missing = 0
    for i, r in enumerate(rows, 1):
        ref = (r.get("reference") or "").strip()
        if not ref:
            continue
        file_name = f"{ref}.pdf"
        payload = {
            "project": args.project,
            "reference": ref,
            "doc_type": (r.get("category") or "").strip(),
            "date": (r.get("date") or "").strip(),
            "title": (r.get("title") or "").strip()[:300],
            "project_id": args.project_id,
        }
        flt = qmodels.Filter(must=[
            qmodels.FieldCondition(
                key="project_id", match=qmodels.MatchValue(value=args.project_id),
            ),
            qmodels.FieldCondition(
                key="file_name", match=qmodels.MatchValue(value=file_name),
            ),
        ])
        try:
            # wait=False keeps it fast; payload is merged onto all of the doc's points.
            client.set_payload(collection_name=args.collection, payload=payload,
                               points=flt, wait=False)
            updated += 1
        except Exception as e:  # noqa: BLE001
            missing += 1
            if missing <= 5:
                print(f"  ! {ref}: {type(e).__name__}: {e}", file=sys.stderr)
        if i % 500 == 0:
            print(f"  {i}/{len(rows)} processed ({updated} set)")

    # Ensure the filtered keys are indexed for fast payload filtering at query time.
    for key in ("project", "doc_type", "reference", "date"):
        try:
            client.create_payload_index(
                collection_name=args.collection, field_name=key,
                field_schema=qmodels.PayloadSchemaType.KEYWORD, wait=False)
        except Exception:
            pass  # already exists / non-fatal

    print(f"\nPayload enrichment done: {updated} documents stamped, {missing} errors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
