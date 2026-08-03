#!/usr/bin/env python3
"""Backfill glossary keys without OCR, extraction, embedding or LLM calls.

Dry-run is the default. Pass ``--apply`` to persist registry and vector payload
metadata. Running the command repeatedly produces the same canonical key set.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.document_registry import get_document_registry
from src.jargon_manager import prepare_query


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", default="")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    registry = get_document_registry()
    records = registry.get_all(project_id=args.project_id or None)
    changed = 0
    for record in records:
        path = Path(record.file_path or "")
        text = ""
        if path.is_file() and path.suffix.lower() in {".txt", ".md", ".csv", ".eml"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
        if not text:
            try:
                from src.chunk_store import get_chunk_store
                rows = get_chunk_store().connection().execute(
                    "SELECT text FROM chunks WHERE project_id=? AND (doc_id=? OR file_name=?)",
                    [record.project_id, record.doc_id, record.file_name],
                ).fetchall()
                text = "\n".join(str(row[0] or "") for row in rows)
            except Exception:
                text = ""
        terms = sorted({key for key, _ in prepare_query(text).matches})
        if terms == sorted(set(record.jargon_terms or [])):
            continue
        changed += 1
        print(f"{record.doc_id}\t{record.file_name}\t{','.join(terms)}")
        if args.apply:
            registry.set_llm_enrichment(record.doc_id, jargon_terms=terms)
            try:
                from src.document_rag import get_document_rag
                get_document_rag().update_payload_scope(
                    record.file_name, {"jargon_terms": terms},
                    project_id=record.project_id, file_id=record.doc_id,
                )
            except Exception:
                pass

    mode = "applied" if args.apply else "dry-run"
    print(f"{mode}: {changed} of {len(records)} document(s) would change")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
