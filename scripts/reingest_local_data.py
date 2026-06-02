"""Batch re-ingest every source file under data/{documents,emails,tables}.

Calls src.file_router.route_file() per file — same code path the upload
endpoint uses — so document_registry, Pinecone vectors, notice metadata,
and the clusterer hook all stay consistent.

After all files are ingested, runs a single force re-cluster so the final
state has real cluster labels instead of whatever the per-file hooks
produced during streaming ingest.

Run:
    PYTHONPATH=. python scripts/reingest_local_data.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DOC_EXTS = {".pdf", ".docx", ".doc", ".txt"}
EMAIL_EXTS = {".eml", ".msg"}
DATA_EXTS = {".xlsx", ".xls", ".csv"}
ALLOWED = DOC_EXTS | EMAIL_EXTS | DATA_EXTS


def _gather() -> list[Path]:
    out: list[Path] = []
    for sub in ("documents", "emails", "tables"):
        folder = ROOT / "data" / sub
        if not folder.exists():
            continue
        for p in sorted(folder.iterdir()):
            if p.is_file() and p.suffix.lower() in ALLOWED:
                out.append(p)
    return out


def main() -> int:
    from src.file_router import route_file

    files = _gather()
    print(f"Found {len(files)} files to ingest")
    print(f"  documents: {sum(1 for f in files if f.suffix.lower() in DOC_EXTS)}")
    print(f"  emails:    {sum(1 for f in files if f.suffix.lower() in EMAIL_EXTS)}")
    print(f"  tables:    {sum(1 for f in files if f.suffix.lower() in DATA_EXTS)}")
    print()

    ok = 0
    err = 0
    t0 = time.time()
    for i, fp in enumerate(files, 1):
        rel = fp.relative_to(ROOT)
        try:
            result = route_file(str(fp))
            tag = "✓" if result.success else "✗"
            extra = ""
            if result.notice_extracted:
                extra += " [notice]"
            if result.tables_extracted:
                extra += f" [{result.tables_extracted} tables]"
            if result.attachments_processed:
                extra += f" [{result.attachments_processed} attachments]"
            if not result.success and result.error:
                extra += f" — {result.error[:80]}"
            print(f"  [{i:3d}/{len(files)}] {tag} {rel}{extra}")
            if result.success:
                ok += 1
            else:
                err += 1
        except Exception as e:
            print(f"  [{i:3d}/{len(files)}] ✗ {rel} — EXCEPTION: {e}")
            err += 1

    elapsed = time.time() - t0
    print(f"\nIngest done: {ok} ok, {err} failed — {elapsed:.1f}s")

    # Final force re-cluster so the label state is consistent.
    print("\nRunning final cluster_all(force=True)…")
    from src.document_clusterer import get_clusterer
    clusterer = get_clusterer()
    result = clusterer.cluster_all(force=True)
    print(f"\n✅ Clusters: {len(result)}")
    for cid, docs in sorted(result.items(), key=lambda x: -len(x[1])):
        entry = clusterer._clusters.get(cid)  # type: ignore[attr-defined]
        label = entry.label if entry else "?"
        types = entry.file_types if entry else []
        print(f"   - {cid:14s} {label!r:32s} {len(docs):3d} docs  {types}")

    return 0 if err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
