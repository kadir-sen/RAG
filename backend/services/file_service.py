"""File upload, listing, and deletion."""

import hashlib
from pathlib import Path
from typing import List

from fastapi import UploadFile

from src.config import DOCUMENTS_DIR, TABLES_DIR, EMAILS_DIR

EXTENSION_MAP = {
    ".pdf": ("document", DOCUMENTS_DIR),
    ".docx": ("document", DOCUMENTS_DIR),
    ".doc": ("document", DOCUMENTS_DIR),
    ".txt": ("document", DOCUMENTS_DIR),
    ".eml": ("email", EMAILS_DIR),
    ".msg": ("email", EMAILS_DIR),
    ".xlsx": ("data", TABLES_DIR),
    ".xls": ("data", TABLES_DIR),
    ".csv": ("data", TABLES_DIR),
}


class FileService:

    async def save(self, file: UploadFile) -> tuple[str, str, bool]:
        """Save uploaded file to disk. Returns (path, doc_id, is_duplicate)."""
        from src.document_registry import get_document_registry
        from src.document_rag import generate_doc_id

        content = await file.read()
        file_size_kb = len(content) // 1024
        ext = Path(file.filename).suffix.lower()
        file_type, target_dir = EXTENSION_MAP.get(ext, ("unknown", DOCUMENTS_DIR))

        # Check for duplicate (same name + same size)
        # If the file was already processed AND is in the RAG index, skip re-upload.
        # Otherwise re-index it (handles cases where indexing failed silently).
        registry = get_document_registry()
        existing = registry.find_duplicate(file.filename, file_size_kb)
        if existing:
            # Verify the file is actually indexed (not just registered)
            actually_indexed = False
            try:
                from src.document_rag import get_document_rag
                rag = get_document_rag()
                actually_indexed = file.filename in rag.file_registry
            except Exception:
                pass
            if not actually_indexed:
                # Also check if it's a data file in DuckDB
                try:
                    from src.data_analyzer_sql import get_data_analyzer
                    analyzer = get_data_analyzer()
                    for tname, info in analyzer.tables.items():
                        if info.get("file_name") == file.filename or info.get("source_file", "").endswith(file.filename):
                            actually_indexed = True
                            break
                except Exception:
                    pass
            if actually_indexed:
                return existing.file_path, existing.doc_id, True
            # File registered but not indexed — re-index it
            import logging
            logging.getLogger("app").info(f"[FileService] Re-indexing {file.filename} (registered but not in index)")
            dest = Path(existing.file_path)
            if dest.exists():
                doc_id = generate_doc_id(str(dest))
                return str(dest), doc_id, False

        # Save to disk
        Path(target_dir).mkdir(parents=True, exist_ok=True)
        dest = Path(target_dir) / file.filename
        dest.write_bytes(content)

        doc_id = generate_doc_id(str(dest))
        registry.register(file.filename, str(dest), file_size_kb, file_type, ext)

        # Sync uploaded file to GCS for persistence across Cloud Run restarts
        try:
            from src.gcs_storage import sync_uploaded_file_to_gcs
            sync_uploaded_file_to_gcs(str(dest))
        except Exception:
            pass

        return str(dest), doc_id, False

    def list_files(self) -> List[dict]:
        """File listing from SINGLE source: document_registry (GCS-backed).
        Enriches with metadata from RAG and catalog but does NOT add files from them.
        This ensures consistent counts across Cloud Run instances.
        """
        files = []
        seen_names = set()

        # ── SINGLE SOURCE: Document Registry (GCS-backed, shared across instances) ──
        try:
            from src.document_registry import get_document_registry
            registry = get_document_registry()
            for rec in registry.get_all():
                if rec.file_name in seen_names:
                    continue
                seen_names.add(rec.file_name)
                files.append({
                    "id": rec.doc_id,
                    "name": rec.file_name,
                    "file_type": rec.file_type or "document",
                    "extension": getattr(rec, 'extension', "") or "",
                    "created_at": getattr(rec, 'created_at', "") or "",
                    "notice_extracted": getattr(rec, 'notice_extracted', False),
                    "pages": None,
                    "ocr_pages": 0,
                    "tables": len(rec.table_names) if hasattr(rec, 'table_names') and rec.table_names else 0,
                    "rows": 0,
                    "status": rec.status,
                    "document_date": "",
                    "sender": "",
                    "recipient": "",
                    "subject": "",
                    "data_table_status": getattr(rec, 'data_table_status', None),
                    "data_tables_count": getattr(rec, 'data_tables_count', 0),
                })
        except Exception:
            pass

        # ── ENRICHMENT ONLY: Add metadata from RAG (page counts, OCR) ──
        try:
            from src.document_rag import get_document_rag
            rag = get_document_rag()
            rag_lookup = {fname: info for fname, info in rag.file_registry.items()}
            for f in files:
                info = rag_lookup.get(f["name"])
                if info:
                    f["pages"] = info.get("page_count", f.get("pages"))
                    f["ocr_pages"] = info.get("ocr_pages", 0)
        except Exception:
            pass

        # ── ENRICHMENT ONLY: Add metadata from catalog (table counts, row counts) ──
        try:
            from src.catalog import get_catalog
            catalog = get_catalog()
            catalog_lookup = {}
            for entry in catalog.entries.values():
                fname = Path(entry.source_file).name
                catalog_lookup[fname] = entry
            for f in files:
                entry = catalog_lookup.get(f["name"])
                if entry:
                    f["file_type"] = "data" if entry.source_type in ("excel", "csv") else f["file_type"]
                    f["tables"] = len(entry.tables)
                    f["rows"] = sum(t.row_count for t in entry.tables)
                    # Backfill for files registered before data_table_status existed.
                    # Catalog membership is the truth for "registered".
                    if not f.get("data_table_status"):
                        f["data_table_status"] = "registered"
                        f["data_tables_count"] = len(entry.tables)
                    if entry.notice_summary:
                        ns = entry.notice_summary
                        f["document_date"] = ns.get("date", "") or ""
                        f["sender"] = ns.get("sender", "") or ""
                        f["recipient"] = ns.get("recipient", "") or ""
                        f["subject"] = ns.get("subject", "") or ""
        except Exception:
            pass

        # ── ENRICHMENT ONLY: Notice metadata for files not enriched by catalog ──
        try:
            from src.notice_extractor import get_notice_extractor
            extractor = get_notice_extractor()
            for f in files:
                if f.get("notice_extracted") and not f.get("document_date"):
                    notice = extractor.load_notice(f["id"])
                    if notice:
                        f["document_date"] = getattr(notice, 'date', "") or ""
                        f["sender"] = getattr(notice, 'sender', "") or ""
                        f["recipient"] = getattr(notice, 'recipient', "") or ""
                        f["subject"] = getattr(notice, 'subject', "") or ""
        except Exception:
            pass

        return files

    def delete(self, file_id: str) -> bool:
        """Delete file by ID. Returns True if found and deleted."""
        # Search through directories
        for dir_path in [DOCUMENTS_DIR, TABLES_DIR, EMAILS_DIR]:
            d = Path(dir_path)
            if not d.exists():
                continue
            for f in d.iterdir():
                fid = hashlib.md5(f.name.encode()).hexdigest()[:12]
                if fid == file_id:
                    f.unlink(missing_ok=True)
                    return True
        return False
