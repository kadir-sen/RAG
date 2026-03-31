"""
Metadata Catalog for table extraction pipeline.
Manages metadata for extracted tables stored as Parquet files.
"""
import json
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

from .config import BASE_DIR
from .logger import logger


# Default paths
PARQUET_DIR = BASE_DIR / "storage" / "parquet"
CATALOG_FILE = PARQUET_DIR / "catalog.json"


@dataclass
class TableMetadata:
    """Metadata for a single extracted table."""
    table_id: str  # Unique identifier
    source_file: str  # Original file path
    source_type: str  # "excel" | "pdf" | "csv"
    table_name: str  # DuckDB view name
    parquet_path: str  # Path to parquet file

    # Extraction details
    sheet_name: Optional[str] = None  # For Excel
    page_number: Optional[int] = None  # For PDF
    table_index: Optional[int] = None  # Multiple tables per page/sheet

    # Table stats
    row_count: int = 0
    column_count: int = 0
    columns: List[str] = field(default_factory=list)

    # Extraction method
    extraction_method: str = "native"  # "native" | "ocr" | "block_detect"
    ocr_applied: bool = False

    # Jargon/abbreviation context for columns
    column_jargon: Dict[str, str] = field(default_factory=dict)  # col_name -> expanded meaning

    # Table-level metadata for query routing (notice-like enrichment)
    description: str = ""  # Human-readable summary (auto-generated)
    semantic_tags: List[str] = field(default_factory=list)  # Keywords for matching
    header_metadata: Dict[str, str] = field(default_factory=dict)  # label -> value from source

    # Auto-extracted insight (from table_insight_extractor)
    insight: Dict[str, Any] = field(default_factory=dict)

    # Human-readable summary (auto-generated)
    summary: str = ""

    # Template tracking
    template_id: Optional[str] = None  # ID of template used for extraction

    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    file_hash: str = ""  # For deduplication


@dataclass
class CatalogEntry:
    """Entry for a source file containing one or more tables."""
    source_file: str
    source_type: str
    file_hash: str
    tables: List[TableMetadata] = field(default_factory=list)
    ingested_at: str = field(default_factory=lambda: datetime.now().isoformat())
    ocr_decision: str = "native"  # "native" | "ocr" | "hybrid"

    # Notice extraction (Phase 2)
    notice_path: Optional[str] = None  # Path to notice JSON
    notice_extracted: bool = False
    notice_summary: Optional[Dict[str, Any]] = None  # Quick summary: date, sender, recipient


class TableCatalog:
    """
    Manages metadata catalog for extracted tables.
    Provides CRUD operations and DuckDB view registration.
    """

    def __init__(self, catalog_path: Optional[Path] = None, parquet_dir: Optional[Path] = None):
        """Initialize catalog."""
        self.catalog_path = catalog_path or CATALOG_FILE
        self.parquet_dir = parquet_dir or PARQUET_DIR

        # Ensure directories exist
        self.parquet_dir.mkdir(parents=True, exist_ok=True)
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)

        # In-memory catalog
        self.entries: Dict[str, CatalogEntry] = {}

        # Load existing catalog
        self._load_catalog()

        logger.info(f"[Catalog] Initialized with {len(self.entries)} entries")

    def _load_catalog(self):
        """Load catalog from disk (try GCS first if local missing)."""
        if not self.catalog_path.exists():
            try:
                from . import gcs_storage
                gcs_storage.sync_catalog_from_gcs()
                gcs_storage.sync_all_parquets_from_gcs()
            except Exception:
                pass
        if not self.catalog_path.exists():
            return

        try:
            with open(self.catalog_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for key, entry_data in data.items():
                tables = []
                for t in entry_data.get("tables", []):
                    tables.append(TableMetadata(**t))

                self.entries[key] = CatalogEntry(
                    source_file=entry_data["source_file"],
                    source_type=entry_data["source_type"],
                    file_hash=entry_data["file_hash"],
                    tables=tables,
                    ingested_at=entry_data.get("ingested_at", ""),
                    ocr_decision=entry_data.get("ocr_decision", "native"),
                    notice_path=entry_data.get("notice_path"),
                    notice_extracted=entry_data.get("notice_extracted", False),
                    notice_summary=entry_data.get("notice_summary"),
                )
        except Exception as e:
            logger.error(f"[Catalog] Error loading catalog: {e}")

    def _save_catalog(self):
        """Persist catalog to disk."""
        try:
            data = {}
            for key, entry in self.entries.items():
                data[key] = {
                    "source_file": entry.source_file,
                    "source_type": entry.source_type,
                    "file_hash": entry.file_hash,
                    "tables": [asdict(t) for t in entry.tables],
                    "ingested_at": entry.ingested_at,
                    "ocr_decision": entry.ocr_decision,
                    "notice_path": entry.notice_path,
                    "notice_extracted": entry.notice_extracted,
                    "notice_summary": entry.notice_summary,
                }

            with open(self.catalog_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.info(f"[Catalog] Saved {len(data)} entries")

            # Sync to GCS synchronously (Cloud Run is stateless!)
            try:
                from . import gcs_storage
                gcs_storage.sync_catalog_to_gcs()
            except Exception:
                pass
        except Exception as e:
            logger.error(f"[Catalog] Error saving catalog: {e}")

    @staticmethod
    def compute_file_hash(file_path: str) -> str:
        """Compute MD5 hash of file for deduplication."""
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception:
            return ""

    def generate_table_id(self, source_file: str, sheet_name: Optional[str] = None,
                          page_number: Optional[int] = None, table_index: int = 0,
                          target_schema: Optional[str] = None) -> str:
        """Generate unique table ID. Uses target_schema prefix when available."""
        file_stem = Path(source_file).stem

        if target_schema:
            # Schema-aware naming: schema_filestem_sheet
            parts = [target_schema]
            # Extract company hint from filename (remove schema-like suffixes)
            hint = file_stem.lower()
            for suffix in ["equipment_log", "equipment log", "manpower_production",
                           "manpower production log", "ipc_sample", "ipc sample"]:
                hint = hint.replace(suffix, "").strip(" _-")
            if hint:
                parts.append(hint)
            if sheet_name:
                parts.append(sheet_name)
        else:
            parts = [file_stem]
            if sheet_name:
                parts.append(sheet_name)

        if page_number is not None:
            parts.append(f"p{page_number}")
        if table_index > 0:
            parts.append(f"t{table_index}")

        # Create hash for uniqueness
        raw = "_".join(parts)
        hash_suffix = hashlib.md5(raw.encode()).hexdigest()[:6]

        # Clean name for DuckDB
        clean = "".join(c if c.isalnum() else "_" for c in raw)
        clean = re.sub(r'_+', '_', clean).strip('_').lower()[:50]

        return f"{clean}_{hash_suffix}"

    def generate_parquet_path(self, table_id: str) -> Path:
        """Generate parquet file path for a table."""
        return self.parquet_dir / f"{table_id}.parquet"

    def add_entry(self, source_file: str, source_type: str,
                  ocr_decision: str = "native") -> CatalogEntry:
        """Add or update a catalog entry for a source file."""
        file_hash = self.compute_file_hash(source_file)
        key = f"{source_type}:{Path(source_file).name}:{file_hash[:8]}"

        # Check if already exists with same hash
        if key in self.entries:
            logger.info(f"[Catalog] Entry already exists: {key}")
            return self.entries[key]

        # Create new entry
        entry = CatalogEntry(
            source_file=source_file,
            source_type=source_type,
            file_hash=file_hash,
            ocr_decision=ocr_decision,
        )
        self.entries[key] = entry
        self._save_catalog()

        logger.info(f"[Catalog] Added entry: {key}")
        return entry

    def add_table(self, entry: CatalogEntry, table_meta: TableMetadata):
        """Add a table to an entry. Skips if table_id already exists."""
        existing_ids = {t.table_id for t in entry.tables}
        if table_meta.table_id in existing_ids:
            logger.info(f"[Catalog] Skipping duplicate table: {table_meta.table_id}")
            return
        entry.tables.append(table_meta)
        self._save_catalog()

        # Sync parquet to GCS
        try:
            from . import gcs_storage
            if table_meta.parquet_path and Path(table_meta.parquet_path).exists():
                gcs_storage.sync_parquet_to_gcs(table_meta.parquet_path)
        except Exception:
            pass

        logger.info(f"[Catalog] Added table: {table_meta.table_name}")

    def get_entry(self, source_file: str) -> Optional[CatalogEntry]:
        """Get catalog entry for a source file."""
        file_name = Path(source_file).name
        for key, entry in self.entries.items():
            if file_name in key:
                return entry
        return None

    def get_all_tables(self) -> List[TableMetadata]:
        """Get all tables from all entries."""
        tables = []
        for entry in self.entries.values():
            tables.extend(entry.tables)
        return tables

    def get_tables_for_source(self, source_file: str) -> List[TableMetadata]:
        """Get all tables for a specific source file."""
        entry = self.get_entry(source_file)
        return entry.tables if entry else []

    def search_by_keyword(self, keyword: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search catalog entries by keyword across tags, descriptions, columns, filenames."""
        from .document_rag import generate_doc_id
        kw = keyword.lower()
        scored: List[tuple] = []  # (score, result_dict)

        seen_sources: set = set()
        for _key, entry in self.entries.items():
            source_name = Path(entry.source_file).name
            if source_name in seen_sources:
                continue
            seen_sources.add(source_name)

            score = 0
            matched_tags: List[str] = []
            matched_desc = ""

            for table in entry.tables:
                # Tag match (highest weight)
                for tag in table.semantic_tags:
                    if kw in tag.lower():
                        score += 3
                        if tag not in matched_tags:
                            matched_tags.append(tag)
                # Description / summary match
                if kw in table.description.lower():
                    score += 2
                    if not matched_desc:
                        matched_desc = table.description
                if kw in table.summary.lower():
                    score += 2
                    if not matched_desc:
                        matched_desc = table.summary
                # Column name match
                for col in table.columns:
                    if kw in col.lower():
                        score += 1

            # Filename match
            if kw in source_name.lower():
                score += 1

            if score == 0:
                continue

            # Best date: notice date > ingested_at
            date = ""
            if entry.notice_summary and entry.notice_summary.get("date"):
                date = entry.notice_summary["date"]
            else:
                date = entry.ingested_at[:10] if entry.ingested_at else ""

            scored.append((score, {
                "doc_id": generate_doc_id(entry.source_file),
                "file_name": source_name,
                "file_path": entry.source_file,
                "file_type": "data",
                "extension": Path(source_name).suffix.lower(),
                "date": date,
                "description": matched_desc,
                "semantic_tags": matched_tags,
                "table_count": len(entry.tables),
                "score": score,
            }))

        # Sort by score DESC, then date DESC
        scored.sort(key=lambda x: (x[0], x[1].get("date", "")), reverse=True)
        return [item[1] for item in scored[:limit]]

    def remove_entry(self, source_file: str):
        """Remove an entry and its parquet files."""
        file_name = Path(source_file).name
        keys_to_remove = [k for k in self.entries.keys() if file_name in k]

        for key in keys_to_remove:
            entry = self.entries[key]

            # Delete parquet files
            for table in entry.tables:
                parquet_path = Path(table.parquet_path)
                if parquet_path.exists():
                    try:
                        parquet_path.unlink()
                        logger.info(f"[Catalog] Deleted parquet: {parquet_path.name}")
                    except Exception as e:
                        logger.error(f"[Catalog] Error deleting parquet: {e}")

            del self.entries[key]

        self._save_catalog()
        logger.info(f"[Catalog] Removed {len(keys_to_remove)} entries for: {file_name}")

    def clear_all(self):
        """Clear all entries and parquet files (local + GCS)."""
        # Delete all local parquet files
        for parquet_file in self.parquet_dir.glob("*.parquet"):
            try:
                parquet_file.unlink()
            except Exception:
                pass

        self.entries.clear()
        self._save_catalog()

        # Clear GCS
        try:
            from . import gcs_storage
            gcs_storage.clear_gcs_tables()
        except Exception:
            pass

        logger.info("[Catalog] Cleared all entries")

    def get_stats(self) -> Dict[str, Any]:
        """Get catalog statistics."""
        all_tables = self.get_all_tables()
        total_rows = sum(t.row_count for t in all_tables)

        return {
            "total_entries": len(self.entries),
            "total_tables": len(all_tables),
            "total_rows": total_rows,
            "by_source_type": self._count_by_source_type(),
            "by_extraction_method": self._count_by_extraction_method(),
        }

    def _count_by_source_type(self) -> Dict[str, int]:
        """Count tables by source type."""
        counts = {}
        for entry in self.entries.values():
            counts[entry.source_type] = counts.get(entry.source_type, 0) + len(entry.tables)
        return counts

    def _count_by_extraction_method(self) -> Dict[str, int]:
        """Count tables by extraction method."""
        counts = {}
        for table in self.get_all_tables():
            counts[table.extraction_method] = counts.get(table.extraction_method, 0) + 1
        return counts

    # Notice management methods (Phase 2)

    def update_notice(self, source_file: str, notice_path: str, notice_summary: Dict[str, Any]):
        """Update notice metadata for an entry."""
        entry = self.get_entry(source_file)
        if entry:
            entry.notice_path = notice_path
            entry.notice_extracted = True
            entry.notice_summary = notice_summary
            self._save_catalog()
            logger.info(f"[Catalog] Updated notice for: {Path(source_file).name}")

    def get_entries_with_notices(self) -> List[CatalogEntry]:
        """Get all entries that have extracted notices."""
        return [e for e in self.entries.values() if e.notice_extracted]

    def get_notice_stats(self) -> Dict[str, Any]:
        """Get notice extraction statistics."""
        with_notices = self.get_entries_with_notices()
        return {
            "total_entries": len(self.entries),
            "with_notices": len(with_notices),
            "without_notices": len(self.entries) - len(with_notices),
        }


# Singleton
_catalog: Optional[TableCatalog] = None


def get_catalog() -> TableCatalog:
    """Get or create TableCatalog singleton."""
    global _catalog
    if _catalog is None:
        _catalog = TableCatalog()
    return _catalog
