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


def _gather(source_dirs: list[Path] | None = None) -> list[Path]:
    if source_dirs is None:
        source_dirs = [ROOT / "data" / sub for sub in ("documents", "emails", "tables")]
    out: list[Path] = []
    for folder in source_dirs:
        if not folder.exists():
            continue
        for p in sorted(folder.iterdir()):
            if p.is_file() and p.suffix.lower() in ALLOWED:
                out.append(p)
    return out


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Batch re-ingest local source files.")
    parser.add_argument("--source-dir", action="append", default=None,
                        help="Directory to ingest from (repeatable). "
                             "Default: data/{documents,emails,tables}.")
    parser.add_argument("--limit", type=int, default=0,
                        help="Only ingest the first N files (validation run).")
    parser.add_argument("--no-cluster", action="store_true",
                        help="Skip the final re-cluster step.")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip files already vectorized in the backend (resumable).")
    parser.add_argument("--corpus", default="",
                        help="Tag ingested tables/docs with this corpus for isolation "
                             "(e.g. 'edinburgh'). Empty → 'demo' default.")
    parser.add_argument("--project-id", required=True)
    args = parser.parse_args()

    # Set the ingest corpus ContextVar so catalog.add_entry / the SQL loader tag
    # every table produced in this run with the right corpus (tenant isolation).
    if args.corpus:
        from src.document_rag import corpus_var
        corpus_var.set(args.corpus.lower())
        print(f"Corpus tag for this run: {args.corpus.lower()}\n")

    from src.file_router import route_file

    source_dirs = [Path(d).resolve() for d in args.source_dir] if args.source_dir else None
    files = _gather(source_dirs)
    if args.limit:
        files = files[: args.limit]
    print(f"Found {len(files)} files to ingest")
    print(f"  documents: {sum(1 for f in files if f.suffix.lower() in DOC_EXTS)}")
    print(f"  emails:    {sum(1 for f in files if f.suffix.lower() in EMAIL_EXTS)}")
    print(f"  tables:    {sum(1 for f in files if f.suffix.lower() in DATA_EXTS)}")
    print()

    # Resumability: skip files whose vectors already exist in the backend, so a
    # long OCR-heavy run can be stopped and re-run without redoing work.
    _rag = None
    if args.skip_existing:
        from src.document_rag import get_document_rag
        _rag = get_document_rag()

    ok = 0
    err = 0
    skipped = 0
    t0 = time.time()
    for i, fp in enumerate(files, 1):
        rel = fp.relative_to(ROOT)
        from src.document_rag import generate_doc_id
        file_id = generate_doc_id(str(fp))
        if _rag is not None and _rag.fetch_doc_vectors(
            fp.name, project_id=args.project_id, file_id=file_id, max_chunks=1,
        ):
            skipped += 1
            if skipped % 200 == 0:
                print(f"  [{i:4d}/{len(files)}] … {skipped} already-indexed skipped")
            continue
        try:
            result = route_file(
                str(fp), project_id=args.project_id, file_id=file_id,
            )
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
    print(f"\nIngest done: {ok} ok, {err} failed, {skipped} skipped — {elapsed:.1f}s")

    if args.no_cluster:
        print("Skipping final cluster step (--no-cluster).")
        return 0 if err == 0 else 1

    # Final force re-cluster so the label state is consistent.
    print("\nRunning final cluster_all(force=True)…")
    from src.document_clusterer import get_clusterer
    clusterer = get_clusterer()
    result = clusterer.cluster_all(force=True, project_id=args.project_id)
    print(f"\n✅ Clusters: {len(result)}")
    for cid, docs in sorted(result.items(), key=lambda x: -len(x[1])):
        entry = clusterer._clusters.get(cid)  # type: ignore[attr-defined]
        label = entry.label if entry else "?"
        types = entry.file_types if entry else []
        print(f"   - {cid:14s} {label!r:32s} {len(docs):3d} docs  {types}")

    return 0 if err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
