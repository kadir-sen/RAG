"""
Converter Registry - Per-company converter storage and matching.
Manages saved converter code that transforms company-specific Excel formats
into standardized target schemas. JSON persistence + GCS sync.
Follows catalog.py singleton + persistence pattern.
"""
import json
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

from .config import CONVERTER_REGISTRY_FILE, CONVERTERS_DIR
from .logger import logger


@dataclass
class ConverterEntry:
    """A saved converter for a specific company format."""
    converter_id: str
    company_id: str
    company_name: str
    target_schema: str
    converter_code: str
    file_name_patterns: List[str] = field(default_factory=list)
    sheet_name_patterns: List[str] = field(default_factory=list)
    column_fingerprint: List[str] = field(default_factory=list)
    sample_files: List[str] = field(default_factory=list)
    test_passed: bool = False
    version: int = 1
    is_active: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


class ConverterRegistry:
    """
    Manages per-company converter persistence.
    JSON-file backed, singleton pattern (follows catalog.py).
    """

    def __init__(self, registry_path: Optional[Path] = None):
        self.registry_path = registry_path or CONVERTER_REGISTRY_FILE
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: Dict[str, ConverterEntry] = {}
        self._load_registry()

    def _load_registry(self) -> None:
        """Load registry from disk (try GCS if local missing)."""
        if not self.registry_path.exists():
            try:
                from .gcs_storage import sync_converter_registry_from_gcs
                sync_converter_registry_from_gcs()
            except Exception:
                pass

        if not self.registry_path.exists():
            return

        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            for key, entry_data in data.items():
                self._entries[key] = ConverterEntry(**entry_data)
            logger.info(f"[ConverterReg] Loaded {len(self._entries)} converters")
        except Exception as e:
            logger.warning(f"[ConverterReg] Failed to load registry: {e}")
            self._entries = {}

    def _save_registry(self) -> None:
        """Persist registry to disk + GCS sync."""
        try:
            data = {k: asdict(v) for k, v in self._entries.items()}
            self.registry_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            # Sync to GCS
            try:
                from .gcs_storage import sync_converter_registry_to_gcs
                sync_converter_registry_to_gcs()
            except Exception:
                pass
        except Exception as e:
            logger.error(f"[ConverterReg] Failed to save registry: {e}")

    def register_converter(
        self,
        company_id: str,
        company_name: str,
        target_schema: str,
        converter_code: str,
        sample_file: str = "",
        column_fingerprint: Optional[List[str]] = None,
        file_name_patterns: Optional[List[str]] = None,
        sheet_name_patterns: Optional[List[str]] = None,
        test_passed: bool = False,
    ) -> str:
        """Register a new converter. Returns converter_id."""
        converter_id = f"conv_{hashlib.md5(f'{company_id}:{target_schema}'.encode()).hexdigest()[:8]}"

        # Check for existing entry and bump version
        version = 1
        existing = self._entries.get(company_id)
        if existing:
            version = existing.version + 1

        entry = ConverterEntry(
            converter_id=converter_id,
            company_id=company_id,
            company_name=company_name,
            target_schema=target_schema,
            converter_code=converter_code,
            file_name_patterns=file_name_patterns or [],
            sheet_name_patterns=sheet_name_patterns or [],
            column_fingerprint=column_fingerprint or [],
            sample_files=[sample_file] if sample_file else [],
            test_passed=test_passed,
            version=version,
        )

        self._entries[company_id] = entry
        self._save_registry()

        logger.info(f"[ConverterReg] Registered converter: {company_id} -> {target_schema} (v{version})")
        return converter_id

    def has_active_converter(self, company_id: str) -> bool:
        """Check if an active converter exists for a company."""
        entry = self._entries.get(company_id)
        return entry is not None and entry.is_active

    def get_active_converter(self, company_id: str) -> Optional[ConverterEntry]:
        """Get the active converter for a company."""
        entry = self._entries.get(company_id)
        if entry and entry.is_active:
            return entry
        return None

    def list_converters(self) -> List[Dict[str, Any]]:
        """List all converters as dicts."""
        return [
            {
                "converter_id": e.converter_id,
                "company_id": e.company_id,
                "company_name": e.company_name,
                "target_schema": e.target_schema,
                "test_passed": e.test_passed,
                "version": e.version,
                "is_active": e.is_active,
                "created_at": e.created_at,
                "sample_files": e.sample_files,
            }
            for e in self._entries.values()
        ]

    def remove_converter(self, converter_id: str) -> None:
        """Remove a converter by ID."""
        key_to_remove = None
        for key, entry in self._entries.items():
            if entry.converter_id == converter_id:
                key_to_remove = key
                break
        if key_to_remove:
            del self._entries[key_to_remove]
            self._save_registry()
            logger.info(f"[ConverterReg] Removed converter: {converter_id}")

    def match_company(self, file_path: str, df_columns: Optional[List[str]] = None) -> Optional[str]:
        """
        Match a file to a company based on filename patterns and column fingerprint.

        Args:
            file_path: Path to the Excel file
            df_columns: Column names from the first sheet (if available)

        Returns:
            company_id if matched, None otherwise
        """
        filename = Path(file_path).name.lower()

        for company_id, entry in self._entries.items():
            if not entry.is_active:
                continue

            # Try filename patterns first
            for pattern in entry.file_name_patterns:
                try:
                    if re.search(pattern, filename, re.IGNORECASE):
                        logger.info(f"[ConverterReg] Matched {filename} -> {company_id} (filename)")
                        return company_id
                except re.error:
                    continue

            # Try column fingerprint
            if df_columns and entry.column_fingerprint:
                cols_lower = [c.lower().strip() for c in df_columns]
                fingerprint_lower = [c.lower().strip() for c in entry.column_fingerprint]
                # Match if >70% of fingerprint columns are present
                matched = sum(1 for fp in fingerprint_lower if fp in cols_lower)
                if len(fingerprint_lower) > 0 and matched / len(fingerprint_lower) >= 0.7:
                    logger.info(f"[ConverterReg] Matched {filename} -> {company_id} (columns)")
                    return company_id

        return None

    def clear_all(self) -> None:
        """Remove all converters."""
        self._entries.clear()
        self._save_registry()
        logger.info("[ConverterReg] Cleared all converters")


# Singleton
_registry: Optional[ConverterRegistry] = None


def get_converter_registry() -> ConverterRegistry:
    """Get or create ConverterRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = ConverterRegistry()
    return _registry
