#!/usr/bin/env python3
"""Backfill project jargon metadata without OCR, extraction or LLM calls.

Dry-run is the default. ``--apply`` updates registry records when they exist and
Qdrant/Pinecone payload metadata for every project-scoped chunk document,
including vector-only legacy corpora. On a single-host deployment run this in a
maintenance container while the API is stopped, because DuckDB permits only one
writing process to own ``chunks.db``.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.document_registry import DocumentRecord, get_document_registry
from src.jargon_manager import get_jargon_manager


def _chunk_documents(project_id: str = "") -> Iterable[Tuple[str, str, str, str]]:
    from src.chunk_store import get_chunk_store

    con = get_chunk_store().connection()
    where = "WHERE project_id<>''"
    params: List[str] = []
    if project_id:
        where += " AND project_id=?"
        params.append(project_id)
    cursor = con.execute(
        # Legacy migrations assigned different doc_id values to pages/chunks of
        # the same source.  Qdrant's durable source identity is project + file
        # name, so aggregate on that pair and keep only one representative id
        # for the optional registry correlation.
        "SELECT project_id,COALESCE(MIN(NULLIF(doc_id,'')),''),file_name,"
        "string_agg(text, '\\n' ORDER BY page_number,chunk_id) "
        f"FROM chunks {where} GROUP BY project_id,file_name "
        "ORDER BY project_id,file_name",
        params,
    )
    while True:
        rows = cursor.fetchmany(25)
        if not rows:
            return
        for row in rows:
            yield str(row[0]), str(row[1]), str(row[2]), str(row[3] or "")


def _registry_indexes(records: Iterable[DocumentRecord]):
    by_doc: Dict[str, List[DocumentRecord]] = defaultdict(list)
    by_name: Dict[str, List[DocumentRecord]] = defaultdict(list)
    for record in records:
        by_doc[record.doc_id].append(record)
        by_name[record.file_name].append(record)
    return by_doc, by_name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-terms", type=int, default=512)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    registry = get_document_registry()
    records = registry.get_all(project_id=args.project_id or None)
    # Legacy registry records have no project_id. Include them as candidates
    # when all projects are requested and correlate them by doc id/file name.
    if not args.project_id:
        records = registry.get_all()
    by_doc, by_name = _registry_indexes(records)
    jargon = get_jargon_manager()
    rag = None

    documents = registry_changes = vector_updates = vector_failures = 0
    matched_documents = 0
    seen_registry = set()
    for project_id, doc_id, file_name, text in _chunk_documents(args.project_id):
        documents += 1
        terms = sorted({key for key, _ in jargon.find_matching_terms(
            text, max_terms=max(1, args.max_terms),
        )})
        if terms:
            matched_documents += 1
        candidates = by_doc.get(doc_id, []) or by_name.get(file_name, [])
        record = next((item for item in candidates if item.project_id == project_id), None)
        if record is None:
            record = next((item for item in candidates if not item.project_id), None)
        if record is not None:
            seen_registry.add(record.doc_id)
            if terms != sorted(set(record.jargon_terms or [])):
                registry_changes += 1
                if args.apply:
                    registry.set_llm_enrichment(record.doc_id, jargon_terms=terms)
        if args.apply:
            if rag is None:
                from src.document_rag import get_document_rag
                rag = get_document_rag()
            # file_name is the indexed, reliable legacy identity; keep file_id
            # empty so older vectors without that newer field are also updated.
            if rag.update_payload_scope(
                file_name, {"jargon_terms": terms}, project_id=project_id,
            ):
                vector_updates += 1
            else:
                vector_failures += 1
        if args.verbose:
            print(f"{project_id}\t{doc_id}\t{file_name}\t{','.join(terms)}")

    # Registry-only text/email records that have no chunk mirror still receive
    # deterministic metadata when their original source remains mounted.
    for record in records:
        if record.doc_id in seen_registry:
            continue
        path = Path(record.file_path or "")
        if not path.is_file() or path.suffix.lower() not in {".txt", ".md", ".csv", ".eml"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        terms = sorted({key for key, _ in jargon.find_matching_terms(
            text, max_terms=max(1, args.max_terms),
        )})
        if terms != sorted(set(record.jargon_terms or [])):
            registry_changes += 1
            if args.apply:
                registry.set_llm_enrichment(record.doc_id, jargon_terms=terms)

    mode = "applied" if args.apply else "dry-run"
    print(
        f"{mode}: documents={documents} matched={matched_documents} "
        f"registry_changes={registry_changes} vector_updates={vector_updates} "
        f"vector_failures={vector_failures}"
    )
    return 1 if args.apply and vector_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
