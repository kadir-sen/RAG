"""Audit Pinecone index coverage: for every unique source document referenced
by an indexed vector, verify that the file is resolvable and openable through
the same path the chat UI uses when a citation is clicked.

Run:
    PYTHONPATH=. python scripts/audit_pinecone.py
    PYTHONPATH=. python scripts/audit_pinecone.py --output audit_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Allow running with `python scripts/audit_pinecone.py` from repo root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import PINECONE_API_KEY, PINECONE_INDEX_NAME  # noqa: E402


def _connect_index():
    if not PINECONE_API_KEY:
        raise RuntimeError("PINECONE_API_KEY is not set")
    from pinecone import Pinecone
    pc = Pinecone(api_key=PINECONE_API_KEY)
    return pc.Index(PINECONE_INDEX_NAME)


def _iter_vector_ids(index, namespace: str, page_size: int = 100):
    """Yield every vector ID in the namespace, paginating via list_paginated."""
    pagination_token = None
    while True:
        resp = index.list_paginated(
            namespace=namespace,
            limit=page_size,
            pagination_token=pagination_token,
        )
        # SDK shape: resp.vectors is iterable of objects with .id
        vectors = getattr(resp, "vectors", None) or []
        for v in vectors:
            vid = getattr(v, "id", None) or (v.get("id") if isinstance(v, dict) else None)
            if vid:
                yield vid
        pagination = getattr(resp, "pagination", None)
        pagination_token = getattr(pagination, "next", None) if pagination else None
        if not pagination_token:
            return


def _fetch_metadata(index, vector_ids: List[str], namespace: str) -> Dict[str, Dict[str, Any]]:
    """Fetch metadata for a batch of vector IDs (Pinecone caps at 1000/req)."""
    out: Dict[str, Dict[str, Any]] = {}
    batch_size = 100
    for i in range(0, len(vector_ids), batch_size):
        batch = vector_ids[i:i + batch_size]
        resp = index.fetch(ids=batch, namespace=namespace)
        vectors = getattr(resp, "vectors", None)
        if vectors is None and isinstance(resp, dict):
            vectors = resp.get("vectors", {})
        if not vectors:
            continue
        for vid, vec in vectors.items():
            md = getattr(vec, "metadata", None)
            if md is None and isinstance(vec, dict):
                md = vec.get("metadata", {})
            out[vid] = dict(md or {})
    return out


def _group_by_doc(metadata_map: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Group vectors by file_name (canonical user-facing identity).

    Pinecone's ``doc_id`` is a per-document LlamaIndex UUID — when the same
    file is indexed twice (e.g. from different host OSes), each ingestion
    generates a fresh UUID, so grouping by ``doc_id`` over-counts. Grouping
    by ``file_name`` collapses those legitimate duplicates.
    """
    groups: Dict[str, Dict[str, Any]] = {}
    for vid, md in metadata_map.items():
        file_name = md.get("file_name") or md.get("doc_id") or vid
        g = groups.setdefault(file_name, {
            "file_name": file_name,
            "doc_ids": set(),
            "file_paths": set(),
            "file_type": md.get("file_type", ""),
            "vector_count": 0,
            "pages": set(),
        })
        g["vector_count"] += 1
        if md.get("doc_id"):
            g["doc_ids"].add(md["doc_id"])
        if md.get("file_path"):
            g["file_paths"].add(md["file_path"])
        page = md.get("page_number")
        if page is not None:
            g["pages"].add(page)
    # serialize sets
    for g in groups.values():
        g["doc_ids"] = sorted(g["doc_ids"])
        g["file_paths"] = sorted(g["file_paths"])
        g["pages"] = sorted(g["pages"])
        g["doc_id"] = g["doc_ids"][0] if g["doc_ids"] else ""
        g["file_path"] = g["file_paths"][0] if g["file_paths"] else ""
        g["duplicate_ingestions"] = len(g["doc_ids"])
    return groups


def _verify_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Run the same resolution path the UI uses when a citation is clicked.

    Tries each Pinecone-stored doc_id and file_path so we report the most
    forgiving result (the citation flow gets one of these at a time).
    """
    from backend.services.document_service import DocumentService
    service = DocumentService()

    # Try every stored file_path to see if at least one resolves on disk
    exists_on_disk = False
    resolved = ""
    for fp in (doc.get("file_paths") or []):
        candidate = service._resolve_path(fp)
        if candidate and Path(candidate).exists():
            resolved = candidate
            exists_on_disk = True
            break
    if not resolved and doc.get("file_paths"):
        resolved = doc["file_paths"][0]

    # Registry presence — try each doc_id and the file_name itself
    registered = False
    try:
        from src.document_registry import get_document_registry
        registry = get_document_registry()
        for did in (doc.get("doc_ids") or []):
            if registry.get(did) is not None:
                registered = True
                break
        if not registered:
            file_name = doc.get("file_name", "")
            for r in registry.get_all():
                if r.file_name == file_name:
                    registered = True
                    break
    except Exception:
        registered = False

    # Try the actual content path with each doc_id
    openable = False
    viewer_type = ""
    viewer_error = "no doc_id worked"
    for did in (doc.get("doc_ids") or [doc.get("doc_id", "")]):
        if not did:
            continue
        try:
            anchor = f"page_{doc['pages'][0]}" if doc.get("pages") else ""
            content = service._get_content_sync(did, anchor)
            err = getattr(content, "error", None) or ""
            if not err:
                openable = True
                viewer_type = getattr(content, "type", "")
                viewer_error = ""
                break
            viewer_error = err
            viewer_type = getattr(content, "type", "")
        except Exception as e:
            viewer_error = f"{type(e).__name__}: {e}"

    return {
        **doc,
        "resolved_path": resolved,
        "exists_on_disk": exists_on_disk,
        "registered": registered,
        "openable": openable,
        "viewer_type": viewer_type,
        "viewer_error": viewer_error,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="audit_report.json",
                        help="Path to write the JSON report")
    parser.add_argument("--namespace", default="__default__",
                        help="Pinecone namespace to audit (default: __default__)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Cap on number of vectors to scan (0 = no cap)")
    args = parser.parse_args()

    print(f"Connecting to Pinecone index '{PINECONE_INDEX_NAME}'...")
    index = _connect_index()
    stats = index.describe_index_stats()
    total = (stats.get("total_vector_count")
             if isinstance(stats, dict)
             else getattr(stats, "total_vector_count", 0))
    print(f"  total vectors: {total}")

    print(f"Listing vector IDs in namespace '{args.namespace}'...")
    ids: List[str] = []
    for vid in _iter_vector_ids(index, args.namespace):
        ids.append(vid)
        if args.limit and len(ids) >= args.limit:
            break
    print(f"  scanned {len(ids)} vector IDs")

    print("Fetching metadata...")
    metadata_map = _fetch_metadata(index, ids, args.namespace)
    print(f"  retrieved metadata for {len(metadata_map)} vectors")

    docs = _group_by_doc(metadata_map)
    print(f"  unique source documents: {len(docs)}")

    print("Verifying each document is openable...")
    verified = []
    for doc in docs.values():
        verified.append(_verify_doc(doc))

    ok = [v for v in verified if v["openable"]]
    broken = [v for v in verified if not v["openable"]]
    unregistered = [v for v in verified if not v["registered"]]
    missing_on_disk = [v for v in verified if not v["exists_on_disk"]]

    report = {
        "index_name": PINECONE_INDEX_NAME,
        "namespace": args.namespace,
        "total_vectors_in_index": total,
        "vectors_scanned": len(metadata_map),
        "unique_documents": len(docs),
        "ok_count": len(ok),
        "broken_count": len(broken),
        "unregistered_count": len(unregistered),
        "missing_on_disk_count": len(missing_on_disk),
        "documents": verified,
    }

    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")

    print()
    print("=" * 60)
    print(f"Index:          {PINECONE_INDEX_NAME}")
    print(f"Unique docs:    {len(docs)}")
    print(f"  openable:     {len(ok)}")
    print(f"  BROKEN:       {len(broken)}")
    print(f"  unregistered: {len(unregistered)}")
    print(f"  missing disk: {len(missing_on_disk)}")
    print("=" * 60)
    if broken:
        print("\nBroken documents (first 20):")
        for v in broken[:20]:
            print(f"  - [{v['doc_id']}] {v['file_name']} — {v['viewer_error'] or 'unknown'}")
    print(f"\nFull report: {args.output}")
    return 0 if not broken else 1


if __name__ == "__main__":
    sys.exit(main())
