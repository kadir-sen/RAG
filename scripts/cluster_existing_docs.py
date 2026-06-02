"""Backfill: cluster every completed document already in the registry.

Pulls chunk embeddings from Pinecone for each document, runs HDBSCAN over
the doc-level centroids, generates LLM labels per cluster, and persists
storage/document_clusters.json. Run once after deploy.

Idempotent — refuses to run if storage/document_clusters.json already
exists unless --force is passed.

Run:
    PYTHONPATH=. python scripts/cluster_existing_docs.py
    PYTHONPATH=. python scripts/cluster_existing_docs.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing storage/document_clusters.json",
    )
    args = parser.parse_args()

    from src.document_clusterer import CLUSTERS_FILE, get_clusterer
    from src.document_registry import get_document_registry

    if CLUSTERS_FILE.exists() and not args.force:
        print(f"❌ {CLUSTERS_FILE} already exists. Re-run with --force to overwrite.")
        return 1

    registry = get_document_registry()
    completed = registry.get_completed()
    eligible = [r for r in completed if r.file_type in ("document", "email")]
    print(f"Found {len(eligible)} eligible docs (of {len(completed)} completed)")

    if not eligible:
        print("Nothing to cluster.")
        return 0

    clusterer = get_clusterer()
    print("Fetching centroids + running HDBSCAN…")
    result = clusterer.cluster_all(force=True)

    print(f"\n✅ Wrote {CLUSTERS_FILE}")
    print(f"   Clusters: {len(result)}")
    for cid, docs in sorted(result.items(), key=lambda x: -len(x[1])):
        entry = clusterer._clusters.get(cid)  # type: ignore[attr-defined]
        label = entry.label if entry else "?"
        print(f"   - {cid:14s} {label!r:30s} {len(docs)} docs")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
