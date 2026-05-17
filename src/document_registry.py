"""
Persistent document library — tracks every file in the system.
JSON-backed at storage/document_registry.json.
"""

import json
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import STORAGE_DIR
from .document_rag import generate_doc_id
from .logger import logger


REGISTRY_FILE = STORAGE_DIR / "document_registry.json"


@dataclass
class DocumentRecord:
    doc_id: str
    file_name: str
    file_path: str
    file_size_kb: int
    file_type: str          # "document" | "email" | "data"
    extension: str          # ".pdf", ".xlsx", etc.
    status: str = "processing"  # "processing" | "completed" | "error"
    table_names: List[str] = field(default_factory=list)
    notice_extracted: bool = False
    file_hash: str = ""     # MD5 hash for strong duplicate detection
    created_at: str = ""
    completed_at: str = ""
    error: Optional[str] = None
    # Excel/CSV ingestion outcome (only meaningful when file_type == "data")
    # "registered"      → at least one parquet/DuckDB table created
    # "no_schema_match" → file processed but no sheet matched a target schema
    # "rag_only"        → not a data file (kept for default Optional in JSON)
    # "error"           → processing crashed
    data_table_status: Optional[str] = None
    data_tables_count: int = 0
    schema_match_details: List[Dict] = field(default_factory=list)


class DocumentRegistry:
    """Singleton JSON-backed document library with duplicate detection."""

    _instance: Optional["DocumentRegistry"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._records: Dict[str, DocumentRecord] = {}
                    inst._file_lock = threading.Lock()
                    inst._load()
                    cls._instance = inst
        return cls._instance

    # ── Persistence ──────────────────────────────────────────

    def _load(self):
        if REGISTRY_FILE.exists():
            try:
                data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
                for doc_id, rec in data.items():
                    self._records[doc_id] = DocumentRecord(**rec)
                logger.info(f"[Registry] Loaded {len(self._records)} documents")
            except Exception as e:
                logger.error(f"[Registry] Failed to load: {e}")

    def _save(self):
        REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {doc_id: asdict(rec) for doc_id, rec in self._records.items()}
        REGISTRY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        # Sync to GCS synchronously (Cloud Run is stateless - data MUST persist!)
        try:
            from .gcs_storage import sync_document_registry_to_gcs
            sync_document_registry_to_gcs()
        except Exception:
            pass

    # ── Public API ───────────────────────────────────────────

    def register(
        self,
        file_name: str,
        file_path: str,
        file_size_kb: int,
        file_type: str,
        extension: str,
    ) -> DocumentRecord:
        """Register a new file. Returns the record (may already exist)."""
        doc_id = generate_doc_id(file_path)
        with self._file_lock:
            if doc_id in self._records:
                return self._records[doc_id]
            # Compute file hash for strong duplicate detection
            file_hash = ""
            try:
                import hashlib
                file_hash = hashlib.md5(open(file_path, "rb").read()).hexdigest()
            except Exception:
                pass
            rec = DocumentRecord(
                doc_id=doc_id,
                file_name=file_name,
                file_path=file_path,
                file_size_kb=file_size_kb,
                file_type=file_type,
                extension=extension,
                status="processing",
                file_hash=file_hash,
                created_at=datetime.now().isoformat(),
            )
            self._records[doc_id] = rec
            self._save()
            logger.info(f"[Registry] Registered: {file_name} ({doc_id})")
            return rec

    def find_duplicate(self, file_name: str, file_size_kb: int,
                       file_path: str = "") -> Optional[DocumentRecord]:
        """Find existing completed record with same name+size or same file hash."""
        # Check by file hash (strongest dedup) if file_path provided
        if file_path:
            try:
                import hashlib
                h = hashlib.md5(open(file_path, "rb").read()).hexdigest()
                for rec in self._records.values():
                    if (getattr(rec, 'file_hash', None) == h
                            and rec.status == "completed"):
                        return rec
            except Exception:
                pass
        # Fallback: name + size
        for rec in self._records.values():
            if (rec.file_name == file_name
                    and rec.file_size_kb == file_size_kb
                    and rec.status == "completed"):
                return rec
        return None

    def mark_completed(
        self,
        doc_id: str,
        table_names: Optional[List[str]] = None,
        notice_extracted: bool = False,
        data_table_status: Optional[str] = None,
        data_tables_count: Optional[int] = None,
        schema_match_details: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        with self._file_lock:
            rec = self._records.get(doc_id)
            if rec:
                rec.status = "completed"
                rec.completed_at = datetime.now().isoformat()
                rec.table_names = table_names or []
                rec.notice_extracted = notice_extracted
                if data_table_status is not None:
                    rec.data_table_status = data_table_status
                if data_tables_count is not None:
                    rec.data_tables_count = data_tables_count
                if schema_match_details is not None:
                    rec.schema_match_details = schema_match_details
                self._save()
                logger.info(f"[Registry] Completed: {rec.file_name}")

    def mark_error(self, doc_id: str, error: str) -> None:
        with self._file_lock:
            rec = self._records.get(doc_id)
            if rec:
                rec.status = "error"
                rec.error = error
                self._save()
                logger.warning(f"[Registry] Error for {rec.file_name}: {error}")

    def delete(self, doc_id: str) -> Optional[DocumentRecord]:
        """Remove a document record. Returns removed record or None."""
        with self._file_lock:
            rec = self._records.pop(doc_id, None)
            if rec:
                self._save()
                logger.info(f"[Registry] Deleted: {rec.file_name}")
            return rec

    def get(self, doc_id: str) -> Optional[DocumentRecord]:
        return self._records.get(doc_id)

    def get_all(self) -> List[DocumentRecord]:
        return list(self._records.values())

    def get_completed(self) -> List[DocumentRecord]:
        return [r for r in self._records.values() if r.status == "completed"]

    def search_by_name(self, keyword: str) -> List[DocumentRecord]:
        """Search completed records by filename substring match (case-insensitive)."""
        kw = keyword.lower()
        return [r for r in self._records.values()
                if r.status == "completed" and kw in r.file_name.lower()]

    def hydrate_from_existing(self, rag_registry: dict, catalog_entries: dict) -> int:
        """Populate registry from existing RAG file_registry + catalog entries.

        One registry record per source file. Catalog entries that share a
        source_file (e.g. an .xlsx indexed once schema-matched and once raw)
        are collapsed: tables merged, the richest metadata wins.

        Returns number of new records added or merged into.
        """
        added = 0
        merged = 0
        with self._file_lock:
            # From RAG file_registry: {file_name: {file_path, file_type, doc_id, ...}}
            for file_name, info in rag_registry.items():
                doc_id = info.get("doc_id", "")
                if doc_id and doc_id not in self._records:
                    fp = info.get("file_path", "")
                    try:
                        size_kb = Path(fp).stat().st_size // 1024 if fp and Path(fp).exists() else 0
                    except OSError:
                        size_kb = 0
                    self._records[doc_id] = DocumentRecord(
                        doc_id=doc_id,
                        file_name=file_name,
                        file_path=fp,
                        file_size_kb=size_kb,
                        file_type="document",
                        extension=info.get("file_type", ""),
                        status="completed",
                        created_at=datetime.now().isoformat(),
                        completed_at=datetime.now().isoformat(),
                    )
                    added += 1

            # Group catalog entries by source_file so multiple tables for the
            # same Excel collapse into a single registry record.
            grouped: Dict[str, List[Any]] = {}
            for _key, entry in catalog_entries.items():
                source_file = getattr(entry, "source_file", "") or ""
                if not source_file:
                    continue
                grouped.setdefault(source_file, []).append(entry)

            for source_file, entries in grouped.items():
                doc_id = generate_doc_id(source_file)
                ext = Path(source_file).suffix.lower()
                try:
                    size_kb = Path(source_file).stat().st_size // 1024 if Path(source_file).exists() else 0
                except OSError:
                    size_kb = 0

                # Aggregate across all entries for this file
                all_table_names: List[str] = []
                notice_extracted = False
                ingested_at = ""
                for entry in entries:
                    for t in getattr(entry, "tables", []) or []:
                        tn = getattr(t, "table_name", "")
                        if tn and tn not in all_table_names:
                            all_table_names.append(tn)
                    if getattr(entry, "notice_extracted", False):
                        notice_extracted = True
                    ia = getattr(entry, "ingested_at", "") or ""
                    if ia and (not ingested_at or ia < ingested_at):
                        ingested_at = ia

                if doc_id not in self._records:
                    self._records[doc_id] = DocumentRecord(
                        doc_id=doc_id,
                        file_name=Path(source_file).name,
                        file_path=source_file,
                        file_size_kb=size_kb,
                        file_type="data" if ext in (".xlsx", ".xls", ".csv") else "document",
                        extension=ext,
                        status="completed",
                        table_names=all_table_names,
                        notice_extracted=notice_extracted,
                        created_at=ingested_at or datetime.now().isoformat(),
                        completed_at=datetime.now().isoformat(),
                    )
                    added += 1
                else:
                    existing = self._records[doc_id]
                    for tn in all_table_names:
                        if tn and tn not in existing.table_names:
                            existing.table_names.append(tn)
                    # Prefer the richer file_size_kb when the existing record is empty
                    if not existing.file_size_kb and size_kb:
                        existing.file_size_kb = size_kb
                    if notice_extracted and not existing.notice_extracted:
                        existing.notice_extracted = True
                    merged += 1

            # Final pass: collapse any legacy records that share the same
            # (file_name, file_path) but live under different doc_ids
            # (the pre-fix data leaves Excel files duplicated this way).
            collapsed = self._collapse_legacy_duplicates_locked()

            if added or merged or collapsed:
                self._save()
                logger.info(
                    f"[Registry] Hydrated: {added} new, {merged} merged, "
                    f"{collapsed} legacy duplicates collapsed"
                )
        return added

    def _collapse_legacy_duplicates_locked(self) -> int:
        """Merge any records that share (file_name, file_path) under different doc_ids.

        Must be called while holding ``_file_lock``. Keeps the record whose
        ``doc_id`` matches ``generate_doc_id(file_path)`` (the canonical one),
        merging tables and richer metadata from the others before deleting them.
        """
        groups: Dict[tuple, List[str]] = {}
        for doc_id, rec in self._records.items():
            key = (rec.file_name, rec.file_path)
            groups.setdefault(key, []).append(doc_id)

        collapsed = 0
        for (file_name, file_path), ids in groups.items():
            if len(ids) < 2:
                continue
            canonical_id = generate_doc_id(file_path) if file_path else ids[0]
            keeper_id = canonical_id if canonical_id in ids else ids[0]
            keeper = self._records[keeper_id]
            for dup_id in ids:
                if dup_id == keeper_id:
                    continue
                dup = self._records.pop(dup_id, None)
                if dup is None:
                    continue
                for tn in dup.table_names:
                    if tn and tn not in keeper.table_names:
                        keeper.table_names.append(tn)
                if not keeper.file_size_kb and dup.file_size_kb:
                    keeper.file_size_kb = dup.file_size_kb
                if dup.notice_extracted and not keeper.notice_extracted:
                    keeper.notice_extracted = True
                collapsed += 1
        return collapsed


def get_document_registry() -> DocumentRegistry:
    """Get or create the singleton DocumentRegistry."""
    return DocumentRegistry()
