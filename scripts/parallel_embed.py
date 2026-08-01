"""Parallel, resumable embedding pass: PDFs -> local embeddings -> Qdrant.

Fans the corpus across N worker processes to use all CPU cores (OCR + embedding
are the bottleneck and parallelize well across documents). Each worker writes
ONLY to the vector store via DocumentRAG.embed_file_to_vectors() — no chunk_store
/ registry / light_graph writes — so there is no cross-process shared-state race
(Qdrant upserts are concurrent-safe). Notices, tables, graph and the lexical
chunk_store are intentionally skipped here; build those in a dedicated batch pass
(Faz 2) afterward.

Resumable: a file whose vectors already exist in the collection is skipped, so the
run can be stopped and re-launched without redoing work.

Run (local Qdrant on :6333, local bge embeddings):
    INGEST_EXTRACT_TABLES=false INGEST_EXTRACT_NOTICES=false \
    VECTOR_STORE_BACKEND=qdrant QDRANT_URL=http://localhost:6333 QDRANT_COLLECTION=coair \
    EMBEDDING_PROVIDER=local EMBEDDING_DEVICE=cpu GOOGLE_API_KEY=dummy \
    PYTHONPATH=. python scripts/parallel_embed.py --source-dir data/edinburgh_tram/pdfs --workers 4
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ALLOWED = {".pdf", ".docx", ".doc", ".txt"}


def _gather(source_dir: Path) -> list[Path]:
    return sorted(p for p in source_dir.iterdir()
                  if p.is_file() and p.suffix.lower() in ALLOWED)


def _worker(worker_id: int, num_workers: int, files: list[str],
            counter, threads: int, project_id: str) -> None:
    # Keep per-process thread pools small so N workers don't oversubscribe cores.
    # Critically, cap tesseract (OMP_THREAD_LIMIT) to 1 — otherwise each worker's
    # OCR tries to grab all cores and N workers thrash (~26s/page instead of ~2-4s).
    os.environ["OMP_THREAD_LIMIT"] = "1"
    os.environ.setdefault("OMP_NUM_THREADS", str(threads))
    try:
        import torch
        torch.set_num_threads(threads)
    except Exception:
        pass

    from src.document_rag import get_document_rag
    rag = get_document_rag()  # builds bge embed model + Qdrant client (per process)

    shard = files[worker_id::num_workers]
    done = skipped = failed = 0
    for fp in shard:
        name = Path(fp).name
        from src.document_rag import generate_doc_id
        file_id = generate_doc_id(fp)
        try:
            if rag.fetch_doc_vectors(
                name, project_id=project_id, file_id=file_id, max_chunks=1,
            ):
                skipped += 1
            else:
                n = rag.embed_file_to_vectors(
                    fp, project_id=project_id, file_id=file_id,
                )
                if n > 0:
                    done += 1
                else:
                    failed += 1
        except Exception as e:  # noqa: BLE001 — one bad file shouldn't kill the worker
            failed += 1
            print(f"  [w{worker_id}] ERROR {name}: {type(e).__name__}: {e}", flush=True)
        with counter.get_lock():
            counter.value += 1
            total = counter.value
        if total % 100 == 0:
            print(f"  … {total} files processed", flush=True)
    print(f"  [w{worker_id}] done: {done} embedded, {skipped} skipped, {failed} failed "
          f"({len(shard)} in shard)", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--project-id", required=True)
    args = parser.parse_args()

    source_dir = Path(args.source_dir).resolve()
    files = [str(p) for p in _gather(source_dir)]
    if args.limit:
        files = files[: args.limit]

    cores = os.cpu_count() or 8
    threads = max(1, cores // max(1, args.workers))
    print(f"Parallel embed: {len(files)} files, {args.workers} workers, "
          f"{threads} threads/worker, collection={os.getenv('QDRANT_COLLECTION')}")

    t0 = time.time()
    counter = mp.Value("i", 0)
    procs = []
    for wid in range(args.workers):
        p = mp.Process(
            target=_worker,
            args=(wid, args.workers, files, counter, threads, args.project_id),
        )
        p.start()
        procs.append(p)
    for p in procs:
        p.join()

    elapsed = time.time() - t0
    print(f"\nParallel embed done: {counter.value} files in {elapsed/60:.1f} min "
          f"({elapsed/max(1, counter.value):.2f} s/file avg)")
    return 0


if __name__ == "__main__":
    mp.set_start_method("spawn")  # torch/MPS are not fork-safe
    raise SystemExit(main())
