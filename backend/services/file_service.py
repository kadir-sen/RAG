"""File upload, listing, and deletion."""

import hashlib
import os
import uuid
from pathlib import Path
from typing import List

from fastapi import UploadFile

from src.config import BASE_DIR, DOCUMENTS_DIR, TABLES_DIR, EMAILS_DIR

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

    @staticmethod
    def _target_dir(project_id: str, file_type: str) -> Path:
        if not project_id:
            return Path({"document": DOCUMENTS_DIR, "email": EMAILS_DIR,
                         "data": TABLES_DIR}.get(file_type, DOCUMENTS_DIR))
        leaf = {"document": "documents", "email": "emails", "data": "tables"}.get(
            file_type, "documents"
        )
        return Path(BASE_DIR) / "data" / "projects" / project_id / leaf

    async def save(self, file: UploadFile, project_id: str = "",
                   username: str = "") -> tuple[str, str, bool]:
        """Save uploaded file to disk. Returns (path, doc_id, is_duplicate)."""
        from src.document_registry import get_document_registry
        from src.document_rag import generate_doc_id

        safe_name = Path(file.filename or "upload.bin").name
        ext = Path(safe_name).suffix.lower()
        file_type = EXTENSION_MAP.get(ext, ("unknown", DOCUMENTS_DIR))[0]
        target_dir = self._target_dir(project_id, file_type)
        target_dir.mkdir(parents=True, exist_ok=True)

        # Stream to disk. Reading the entire upload into RAM made a 500-file
        # batch capable of exhausting even the upgraded 8 GB host.
        temp = target_dir / f".{uuid.uuid4().hex}.upload"
        total = 0
        with temp.open("wb") as handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                total += len(chunk)
        file_size_kb = total // 1024

        # Check for duplicate (same name + same size)
        # If the file was already processed AND is in the RAG index, skip re-upload.
        # Otherwise re-index it (handles cases where indexing failed silently).
        registry = get_document_registry()
        existing = registry.find_duplicate(
            safe_name, file_size_kb, file_path=str(temp), project_id=project_id,
        )
        if existing:
            if existing.status == "completed":
                temp.unlink(missing_ok=True)
                if username and project_id:
                    from src.billing_store import get_billing_store
                    get_billing_store().register_storage(
                        username=username, project_id=project_id,
                        file_id=existing.doc_id, file_path=existing.file_path,
                        size_bytes=total,
                    )
                return existing.file_path, existing.doc_id, True

        dest = target_dir / safe_name
        if dest.exists():
            hasher = hashlib.sha256()
            with temp.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    hasher.update(block)
            digest = hasher.hexdigest()[:10]
            dest = target_dir / f"{dest.stem}-{digest}{dest.suffix}"
        os.replace(temp, dest)

        doc_id = generate_doc_id(str(dest))
        storage_registered = False
        try:
            if username and project_id:
                from src.billing_store import get_billing_store
                get_billing_store().register_storage(
                    username=username, project_id=project_id, file_id=doc_id,
                    file_path=str(dest), size_bytes=total,
                )
                storage_registered = True
            registry.register(dest.name, str(dest), file_size_kb, file_type, ext,
                              project_id=project_id)
        except Exception:
            if storage_registered:
                from src.billing_store import get_billing_store
                get_billing_store().release_storage(project_id=project_id, file_id=doc_id)
            dest.unlink(missing_ok=True)
            raise

        # Sync uploaded file to GCS for persistence across Cloud Run restarts
        try:
            from src.gcs_storage import sync_uploaded_file_to_gcs
            sync_uploaded_file_to_gcs(str(dest))
        except Exception:
            pass

        return str(dest), doc_id, False

    def list_files(self, corpus: str = "", project_id: str | None = None) -> List[dict]:
        """File listing from SINGLE source: document_registry (GCS-backed).
        Enriches with metadata from RAG and catalog but does NOT add files from them.
        This ensures consistent counts across Cloud Run instances.

        ``corpus`` (e.g. "demo") drops files whose catalog entry belongs to a
        different corpus, so the demo account never sees edinburgh data tables.
        Pure documents (no catalog entry) default to the demo corpus.
        """
        files = []
        seen_names = set()

        # ── SINGLE SOURCE: Document Registry (GCS-backed, shared across instances) ──
        try:
            from src.document_registry import get_document_registry
            registry = get_document_registry()
            for rec in registry.get_all(project_id=project_id):
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
                    "corpus": "demo",       # default; overridden from catalog below
                    "columns": [],
                    "sheets": 0,
                })
        except Exception:
            pass

        # ── ENRICHMENT ONLY: Add metadata from RAG (page counts, OCR) ──
        try:
            from src.document_rag import get_document_rag
            rag = get_document_rag()
            rag_lookup = {
                fname: info for fname, info in rag.file_registry.items()
                if not project_id or (info.get("project_id", "") or "") == project_id
            }
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
                if project_id and (getattr(entry, "project_id", "") or "") != project_id:
                    continue
                fname = Path(entry.source_file).name
                catalog_lookup[fname] = entry
            for f in files:
                entry = catalog_lookup.get(f["name"])
                if entry:
                    f["file_type"] = "data" if entry.source_type in ("excel", "csv") else f["file_type"]
                    f["tables"] = len(entry.tables)
                    f["rows"] = sum(t.row_count for t in entry.tables)
                    f["corpus"] = (getattr(entry, "corpus", "demo") or "demo").lower()
                    f["sheets"] = len(entry.tables)
                    # Short column summary from the first table (viewer shows full schema).
                    if entry.tables:
                        f["columns"] = list(entry.tables[0].columns or [])[:8]
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

        # Per-corpus isolation: drop files whose catalog corpus differs from the
        # requested one (edinburgh data tables never surface in the demo list).
        if corpus:
            c = corpus.lower()
            files = [f for f in files if (f.get("corpus") or "demo") == c]

        return files

    def delete(self, file_id: str, project_id: str = "") -> bool:
        """Delete file by ID. Returns True if found and deleted."""
        try:
            from src.document_registry import get_document_registry
            rec = get_document_registry().get(file_id)
            if rec and project_id and getattr(rec, "project_id", "") != project_id:
                return False
            if rec and Path(rec.file_path).is_file():
                Path(rec.file_path).unlink(missing_ok=True)
                return True
        except Exception:
            pass
        # Search through directories
        dirs = ([self._target_dir(project_id, t) for t in ("document", "data", "email")]
                if project_id else [Path(DOCUMENTS_DIR), Path(TABLES_DIR), Path(EMAILS_DIR)])
        for dir_path in dirs:
            d = Path(dir_path)
            if not d.exists():
                continue
            for f in d.iterdir():
                fid = hashlib.md5(f.name.encode()).hexdigest()[:12]
                if fid == file_id:
                    f.unlink(missing_ok=True)
                    return True
        return False
