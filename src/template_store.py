"""
Template Store for Excel table extraction.

Manages reusable extraction templates that capture the structural fingerprint
of Excel file formats. When a user confirms an extraction, the format is saved
as a template and automatically applied to similar files in the future.

Storage: JSON file alongside the catalog (storage/parquet/templates.json).
Pattern: Follows TableCatalog singleton + JSON persistence from catalog.py.
"""
import json
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

from .config import TEMPLATE_FILE, TEMPLATE_CONFIDENCE_THRESHOLD
from .logger import logger


@dataclass
class SheetTemplate:
    """Template for extracting a single sheet within an Excel file."""
    sheet_name_pattern: str          # regex or exact match for sheet tab name
    header_rows: List[int]           # 0-indexed row indices forming the header
    data_start_row: int              # 0-indexed first data row
    col_start: int                   # 0-indexed first data column
    col_end: int                     # 0-indexed last data column (inclusive)
    column_names: List[str]          # normalized column names after merge
    column_count: int
    column_types: Dict[str, str] = field(default_factory=dict)  # col -> "string"|"numeric"|"mixed"
    is_multi_row_header: bool = False
    has_metadata_header: bool = False
    metadata_labels: List[str] = field(default_factory=list)
    has_serial_column: bool = False
    has_summary_rows: bool = False
    extraction_method: str = "full_sheet"  # which tier originally produced this


@dataclass
class FileTemplate:
    """Template for an entire Excel file type."""
    template_id: str                 # "tmpl_" + hash
    name: str                        # human-readable: "DPR Daily Report"
    category: str                    # "dpr"|"invoice"|"manpower"|"progress"|"custom"
    file_name_pattern: str           # regex for matching file names
    sheet_name_patterns: List[str]   # expected sheet names (order matters)
    sheet_templates: Dict[str, SheetTemplate] = field(default_factory=dict)
    confidence_threshold: float = TEMPLATE_CONFIDENCE_THRESHOLD
    source_file: str = ""
    match_count: int = 0
    version: int = 1
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


def _generate_template_id(name: str, source_file: str) -> str:
    """Generate a unique template ID from name + source file."""
    raw = f"{name}:{source_file}:{datetime.now().isoformat()}"
    h = hashlib.md5(raw.encode()).hexdigest()[:8]
    return f"tmpl_{h}"


def _sheet_template_to_dict(st: SheetTemplate) -> dict:
    """Convert SheetTemplate to JSON-serializable dict."""
    return asdict(st)


def _sheet_template_from_dict(d: dict) -> SheetTemplate:
    """Reconstruct SheetTemplate from dict."""
    return SheetTemplate(**d)


def _file_template_to_dict(ft: FileTemplate) -> dict:
    """Convert FileTemplate to JSON-serializable dict."""
    result = {
        "template_id": ft.template_id,
        "name": ft.name,
        "category": ft.category,
        "file_name_pattern": ft.file_name_pattern,
        "sheet_name_patterns": ft.sheet_name_patterns,
        "confidence_threshold": ft.confidence_threshold,
        "source_file": ft.source_file,
        "match_count": ft.match_count,
        "version": ft.version,
        "created_at": ft.created_at,
        "updated_at": ft.updated_at,
        "sheet_templates": {
            k: _sheet_template_to_dict(v)
            for k, v in ft.sheet_templates.items()
        },
    }
    return result


def _file_template_from_dict(d: dict) -> FileTemplate:
    """Reconstruct FileTemplate from dict."""
    sheet_templates = {}
    for k, v in d.get("sheet_templates", {}).items():
        sheet_templates[k] = _sheet_template_from_dict(v)

    return FileTemplate(
        template_id=d["template_id"],
        name=d["name"],
        category=d.get("category", "custom"),
        file_name_pattern=d.get("file_name_pattern", ""),
        sheet_name_patterns=d.get("sheet_name_patterns", []),
        sheet_templates=sheet_templates,
        confidence_threshold=d.get("confidence_threshold", TEMPLATE_CONFIDENCE_THRESHOLD),
        source_file=d.get("source_file", ""),
        match_count=d.get("match_count", 0),
        version=d.get("version", 1),
        created_at=d.get("created_at", ""),
        updated_at=d.get("updated_at", ""),
    )


class TemplateStore:
    """
    Manages extraction templates with JSON persistence.
    Singleton pattern matching TableCatalog.
    """

    def __init__(self, template_path: Optional[Path] = None):
        self.template_path = Path(template_path) if template_path else TEMPLATE_FILE
        self.templates: Dict[str, FileTemplate] = {}
        self._load()

    # ── Persistence ─────────────────────────────────────────────

    def _load(self):
        """Load templates from JSON file."""
        if not self.template_path.exists():
            self.templates = {}
            return

        try:
            with open(self.template_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for tid, tdict in data.get("templates", {}).items():
                self.templates[tid] = _file_template_from_dict(tdict)

            logger.info(f"[TemplateStore] Loaded {len(self.templates)} template(s)")
        except Exception as e:
            logger.error(f"[TemplateStore] Failed to load templates: {e}")
            self.templates = {}

    def _save(self):
        """Save templates to JSON file."""
        self.template_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version": 1,
            "templates": {
                tid: _file_template_to_dict(ft)
                for tid, ft in self.templates.items()
            },
        }

        try:
            with open(self.template_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"[TemplateStore] Saved {len(self.templates)} template(s)")
        except Exception as e:
            logger.error(f"[TemplateStore] Failed to save templates: {e}")

    # ── CRUD ────────────────────────────────────────────────────

    def add_template(self, template: FileTemplate) -> str:
        """
        Add a new template. Validates before saving.
        Returns the template_id.
        """
        errors = self._validate(template)
        if errors:
            raise ValueError(f"Invalid template: {'; '.join(errors)}")

        self.templates[template.template_id] = template
        self._save()
        logger.info(f"[TemplateStore] Added template: {template.name} ({template.template_id})")
        return template.template_id

    def get_template(self, template_id: str) -> Optional[FileTemplate]:
        """Get a template by ID."""
        return self.templates.get(template_id)

    def remove_template(self, template_id: str) -> bool:
        """Remove a template by ID. Returns True if found and removed."""
        if template_id in self.templates:
            name = self.templates[template_id].name
            del self.templates[template_id]
            self._save()
            logger.info(f"[TemplateStore] Removed template: {name} ({template_id})")
            return True
        return False

    def update_template(self, template_id: str, **updates) -> bool:
        """Update specific fields of a template. Increments version."""
        ft = self.templates.get(template_id)
        if not ft:
            return False

        for key, value in updates.items():
            if hasattr(ft, key):
                setattr(ft, key, value)

        ft.version += 1
        ft.updated_at = datetime.now().isoformat()
        self._save()
        logger.info(f"[TemplateStore] Updated template: {ft.name} v{ft.version}")
        return True

    def record_match(self, template_id: str):
        """Increment match_count for a template."""
        ft = self.templates.get(template_id)
        if ft:
            ft.match_count += 1
            self._save()

    def list_templates(self) -> List[Dict[str, Any]]:
        """Return summary list for UI display."""
        result = []
        for ft in self.templates.values():
            result.append({
                "template_id": ft.template_id,
                "name": ft.name,
                "category": ft.category,
                "sheet_count": len(ft.sheet_templates),
                "match_count": ft.match_count,
                "version": ft.version,
                "source_file": ft.source_file,
                "created_at": ft.created_at,
            })
        return sorted(result, key=lambda x: x["match_count"], reverse=True)

    # ── Validation ──────────────────────────────────────────────

    def _validate(self, template: FileTemplate) -> List[str]:
        """Validate a template before saving. Returns list of errors."""
        errors = []

        if not template.template_id:
            errors.append("template_id is required")
        if not template.name:
            errors.append("name is required")
        if not template.sheet_templates:
            errors.append("At least one sheet template is required")

        for key, st in template.sheet_templates.items():
            if len(st.column_names) < 2:
                errors.append(f"Sheet '{key}': needs at least 2 columns")
            if not st.header_rows:
                errors.append(f"Sheet '{key}': header_rows is required")
            if st.data_start_row <= max(st.header_rows, default=-1):
                errors.append(f"Sheet '{key}': data_start_row must be after header rows")

        return errors


# ── Singleton ───────────────────────────────────────────────────

_store: Optional[TemplateStore] = None


def get_template_store(template_path: Optional[Path] = None) -> TemplateStore:
    """Get or create the singleton TemplateStore."""
    global _store
    if _store is None:
        _store = TemplateStore(template_path)
    return _store


def reset_template_store():
    """Reset singleton (for testing)."""
    global _store
    _store = None
