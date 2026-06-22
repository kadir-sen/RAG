"""Backfill LLM enrichment over an already-ingested corpus (no PDFs, no re-embed).

The fast embed pass populated only vectors. The learning layers (event-timeline,
jargon, doc_type classification) need the unified LLM enrichment, which was skipped.
This script reads each document's text FROM THE CHUNK STORE (mirrored at ingest /
backfilled from Qdrant — so it works on the server without the original PDFs), runs
the one cheap unified enrichment call per document, and writes
storage/enrichment/{doc_id}.json (events + new_terms + doc_type + summary).

Needs the Gemini LLM → run on the server (Py3.11), not the local Py3.14 box.
Resumable: documents already enriched are skipped. Cheap: ~first 6k chars per doc,
cached. Feed the result into scripts/build_event_timeline.py afterward.

Run (on server, inside the app env):
    PYTHONPATH=. python scripts/enrich_corpus.py [--limit N]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _doc_texts_from_chunk_store(max_chars: int) -> dict[str, str]:
    """file_name -> concatenated chunk text (page order), capped at max_chars."""
    from src.chunk_store import get_chunk_store
    con = get_chunk_store().connection()
    rows = con.execute(
        "SELECT file_name, page_number, text FROM chunks ORDER BY file_name, page_number"
    ).fetchall()
    out: dict[str, list[str]] = {}
    for file_name, _page, text in rows:
        if not file_name or not text:
            continue
        bucket = out.setdefault(file_name, [])
        # stop accumulating once we have enough for this doc
        if sum(len(t) for t in bucket) < max_chars:
            bucket.append(text)
    return {fn: ("\n".join(parts))[:max_chars] for fn, parts in out.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-chars", type=int, default=6000)
    args = parser.parse_args()

    from src import file_router
    from src.config import STORAGE_DIR
    from src.document_rag import generate_doc_id

    enrich_dir = Path(STORAGE_DIR) / "enrichment"
    enrich_dir.mkdir(parents=True, exist_ok=True)

    texts = _doc_texts_from_chunk_store(args.max_chars)
    items = sorted(texts.items())
    if args.limit:
        items = items[: args.limit]
    print(f"{len(items)} documents to enrich (chunk-store text).")

    done = skipped = 0
    for i, (file_name, text) in enumerate(items, 1):
        doc_id = generate_doc_id(file_name)
        if (enrich_dir / f"{doc_id}.json").exists():
            skipped += 1
            continue
        # _enrich_document_llm derives doc_id from its first arg via generate_doc_id,
        # so passing file_name keeps the side-store id stable and PDF-free.
        # set_scope_payload=False: a per-doc Qdrant set_payload across the whole
        # collection would time out over thousands of docs — scope payloads are
        # backfilled separately via scripts/enrich_payload.py (which indexes first).
        file_router._enrich_document_llm(file_name, text, set_scope_payload=False)
        done += 1
        if i % 100 == 0:
            print(f"  [{i}/{len(items)}] {done} enriched, {skipped} skipped")

    n_files = len(list(enrich_dir.glob("*.json")))
    print(f"\nEnrichment done: {done} new, {skipped} skipped → {n_files} files in {enrich_dir}")
    print("Next: PYTHONPATH=. python scripts/build_event_timeline.py --project \"Edinburgh Tram Inquiry\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
