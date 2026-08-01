"""Backfill the lexical chunk_store (DuckDB BM25) from existing Qdrant vectors.

The fast parallel embed pass wrote ONLY dense vectors to Qdrant — it skipped the
chunk_store that powers the lexical (BM25/keyword) retrieval lane. Without it,
hybrid retrieval degrades to dense-only, which is the weaker setup for exact-term
queries (reference codes, names) and a key hallucination guard is inactive.

This restores the lexical lane WITHOUT re-embedding: it scrolls every Qdrant point,
pulls the chunk text out of the LlamaIndex payload (`_node_content`), and mirrors it
into the chunk_store. Idempotent (stable chunk_id; re-runs are no-ops).

Run:
    QDRANT_URL=http://localhost:6333 QDRANT_COLLECTION=coair \
    PYTHONPATH=. python scripts/backfill_chunkstore.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _text_from_payload(md: dict) -> str:
    nc = md.get("_node_content")
    if nc:
        try:
            return json.loads(nc).get("text", "")
        except Exception:
            return nc if isinstance(nc, str) else ""
    return md.get("text", "") or ""


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", default=os.getenv("QDRANT_COLLECTION", "coair"))
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"))
    parser.add_argument("--batch", type=int, default=2000)
    args = parser.parse_args()

    from qdrant_client import QdrantClient
    from src.chunk_store import get_chunk_store

    client = QdrantClient(url=args.qdrant_url, timeout=120.0, check_compatibility=False)
    store = get_chunk_store()
    print(f"chunk_store before: {store.count()} chunks")

    off = None
    seen = inserted = 0
    payload_fields = [
        "_node_content", "text", "file_name", "page_number", "doc_id", "project_id",
    ]
    while True:
        points, off = client.scroll(args.collection, limit=args.batch, offset=off,
                                     with_payload=payload_fields, with_vectors=False)
        rows = []
        for p in points:
            md = p.payload or {}
            text = _text_from_payload(md)
            project_id = str(md.get("project_id") or "").strip()
            if not text or not project_id:
                continue
            rows.append({
                "doc_id": md.get("doc_id", ""),
                "file_name": md.get("file_name", "Unknown"),
                "page_number": md.get("page_number", 1),
                "text": text,
                "project_id": project_id,
            })
        seen += len(points)
        inserted += store.add_chunks(rows)
        print(f"  scanned {seen} points → chunk_store {store.count()}")
        if off is None:
            break

    print(f"\nBackfill done: {store.count()} chunks total (+{inserted} new). "
          f"Lexical/BM25 lane is now active for hybrid retrieval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
