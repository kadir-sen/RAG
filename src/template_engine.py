"""
Template Engine - Storage and matching for Excel extraction templates.

Manages reusable extraction templates that capture the structural fingerprint
of Excel file formats. When a user confirms an extraction, the format is saved
as a template and automatically applied to similar files in the future.

Matching uses a 3-stage scoring funnel (cheap to expensive):
  Stage 1: File-level pre-filter (filename, sheet names)     -> 0-30 pts
  Stage 2: Column fingerprint (header similarity)            -> 0-50 pts
  Stage 3: Structural markers (metadata, serial col, etc.)   -> 0-20 pts

Total: 0-100. Files scoring above confidence_threshold are auto-matched.
"""
import json
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict

from .config import (
    TEMPLATE_FILE,
    TEMPLATE_CONFIDENCE_THRESHOLD,
    TEMPLATE_REVIEW_THRESHOLD,
)
from .logger import logger


# ── Template Data Classes ───────────────────────────────────

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
    column_types: Dict[str, str] = field(default_factory=dict)
    is_multi_row_header: bool = False
    has_metadata_header: bool = False
    metadata_labels: List[str] = field(default_factory=list)
    has_serial_column: bool = False
    has_summary_rows: bool = False
    extraction_method: str = "full_sheet"


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


# ── Serialization Helpers ───────────────────────────────────

def _generate_template_id(name: str, source_file: str) -> str:
    """Generate a unique template ID from name + source file."""
    raw = f"{name}:{source_file}:{datetime.now().isoformat()}"
    h = hashlib.md5(raw.encode()).hexdigest()[:8]
    return f"tmpl_{h}"


def _sheet_template_to_dict(st: SheetTemplate) -> dict:
    return asdict(st)


def _sheet_template_from_dict(d: dict) -> SheetTemplate:
    return SheetTemplate(**d)


def _file_template_to_dict(ft: FileTemplate) -> dict:
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


# ── Template Store ──────────────────────────────────────────

class TemplateStore:
    """
    Manages extraction templates with JSON persistence.
    Singleton pattern matching TableCatalog.
    """

    def __init__(self, template_path: Optional[Path] = None):
        self.template_path = Path(template_path) if template_path else TEMPLATE_FILE
        self.templates: Dict[str, FileTemplate] = {}
        self._load()

    def _load(self):
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

    def add_template(self, template: FileTemplate) -> str:
        errors = self._validate(template)
        if errors:
            raise ValueError(f"Invalid template: {'; '.join(errors)}")
        self.templates[template.template_id] = template
        self._save()
        logger.info(f"[TemplateStore] Added template: {template.name} ({template.template_id})")
        return template.template_id

    def get_template(self, template_id: str) -> Optional[FileTemplate]:
        return self.templates.get(template_id)

    def remove_template(self, template_id: str) -> bool:
        if template_id in self.templates:
            name = self.templates[template_id].name
            del self.templates[template_id]
            self._save()
            logger.info(f"[TemplateStore] Removed template: {name} ({template_id})")
            return True
        return False

    def update_template(self, template_id: str, **updates) -> bool:
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
        ft = self.templates.get(template_id)
        if ft:
            ft.match_count += 1
            self._save()

    def list_templates(self) -> List[Dict[str, Any]]:
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

    def _validate(self, template: FileTemplate) -> List[str]:
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


# ── Singleton ───────────────────────────────────────────────

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


# ── Matcher Helpers ─────────────────────────────────────────

def _jaccard_similarity(set_a: set, set_b: set) -> float:
    """Jaccard similarity between two sets. Returns 0.0-1.0."""
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def _normalize_col_name(name: str) -> str:
    """Normalize a column name for comparison."""
    if not name:
        return ""
    s = str(name).lower().strip()
    s = re.sub(r'[^a-z0-9]', '_', s)
    s = re.sub(r'_+', '_', s).strip('_')
    return s


def _sheet_name_matches(pattern: str, actual: str) -> bool:
    """Check if actual sheet name matches pattern (regex or exact)."""
    if not pattern or not actual:
        return False
    if pattern.lower() == actual.lower():
        return True
    try:
        return bool(re.search(pattern, actual, re.IGNORECASE))
    except re.error:
        return False


# ── Template Matcher ────────────────────────────────────────

class TemplateMatcher:
    """Matches incoming Excel files against stored templates."""

    def __init__(self, store: TemplateStore):
        self.store = store

    def find_best_template(
        self,
        file_path: str,
        sheet_names: List[str],
        sheet_matrices: Optional[Dict[str, list]] = None,
    ) -> Optional[Tuple[FileTemplate, float]]:
        """
        Find the best matching template for an Excel file.
        Returns (template, score) tuple if above review threshold, None otherwise.
        """
        if not self.store.templates:
            return None

        best_template = None
        best_score = 0.0

        for ft in self.store.templates.values():
            score = self._score_template(ft, file_path, sheet_names, sheet_matrices)
            if score > best_score:
                best_score = score
                best_template = ft

        if best_template and best_score >= TEMPLATE_REVIEW_THRESHOLD:
            logger.info(
                f"[TemplateMatcher] Best match: '{best_template.name}' "
                f"(score={best_score:.1f}, threshold={best_template.confidence_threshold})"
            )
            return best_template, best_score

        return None

    def is_auto_match(self, template: FileTemplate, score: float) -> bool:
        return score >= template.confidence_threshold * 100

    def find_sheet_template(
        self, template: FileTemplate, sheet_name: str
    ) -> Optional[SheetTemplate]:
        for pattern, st in template.sheet_templates.items():
            if _sheet_name_matches(pattern, sheet_name):
                return st
        return None

    def _score_template(
        self, template: FileTemplate, file_path: str,
        sheet_names: List[str], sheet_matrices: Optional[Dict[str, list]],
    ) -> float:
        score = 0.0
        s1 = self._score_file_level(template, file_path, sheet_names)
        score += s1
        if s1 < 5:
            return score
        if sheet_matrices:
            s2 = self._score_column_fingerprint(template, sheet_names, sheet_matrices)
            score += s2
            s3 = self._score_structural_markers(template, sheet_names, sheet_matrices)
            score += s3
        return score

    def _score_file_level(
        self, template: FileTemplate, file_path: str, sheet_names: List[str],
    ) -> float:
        score = 0.0
        filename = Path(file_path).name
        if template.file_name_pattern:
            try:
                if re.search(template.file_name_pattern, filename, re.IGNORECASE):
                    score += 15.0
            except re.error:
                pass
        if template.sheet_name_patterns:
            matched = 0
            for pattern in template.sheet_name_patterns:
                for actual in sheet_names:
                    if _sheet_name_matches(pattern, actual):
                        matched += 1
                        break
            if template.sheet_name_patterns:
                ratio = matched / len(template.sheet_name_patterns)
                score += ratio * 15.0
        return score

    def _score_column_fingerprint(
        self, template: FileTemplate, sheet_names: List[str],
        sheet_matrices: Dict[str, list],
    ) -> float:
        if not template.sheet_templates:
            return 0.0

        total_score = 0.0
        matched_sheets = 0

        for pattern, st in template.sheet_templates.items():
            actual_sheet = None
            for sn in sheet_names:
                if _sheet_name_matches(pattern, sn):
                    actual_sheet = sn
                    break
            if not actual_sheet or actual_sheet not in sheet_matrices:
                continue

            matrix = sheet_matrices[actual_sheet]
            matched_sheets += 1

            actual_cols = self._extract_header_columns(
                matrix, st.header_rows, st.col_start, st.col_end
            )

            template_col_set = {_normalize_col_name(c) for c in st.column_names if c}
            actual_col_set = {_normalize_col_name(c) for c in actual_cols if c}
            jaccard = _jaccard_similarity(template_col_set, actual_col_set)
            total_score += jaccard * 35.0

            if st.column_count > 0:
                diff = abs(len(actual_cols) - st.column_count)
                if diff == 0:
                    total_score += 10.0
                elif diff <= 3:
                    total_score += 10.0 * (1.0 - diff / 4.0)

            if st.column_types and actual_cols:
                actual_types = self._infer_column_types(
                    matrix, st.data_start_row, st.col_start, st.col_end
                )
                template_numeric_ratio = sum(
                    1 for t in st.column_types.values() if t == "numeric"
                ) / max(len(st.column_types), 1)
                actual_numeric_ratio = sum(
                    1 for t in actual_types.values() if t == "numeric"
                ) / max(len(actual_types), 1)
                type_similarity = 1.0 - abs(template_numeric_ratio - actual_numeric_ratio)
                total_score += type_similarity * 5.0

            break

        if matched_sheets == 0:
            return 0.0
        return total_score

    def _score_structural_markers(
        self, template: FileTemplate, sheet_names: List[str],
        sheet_matrices: Dict[str, list],
    ) -> float:
        if not template.sheet_templates:
            return 0.0

        total_score = 0.0
        for pattern, st in template.sheet_templates.items():
            actual_sheet = None
            for sn in sheet_names:
                if _sheet_name_matches(pattern, sn):
                    actual_sheet = sn
                    break
            if not actual_sheet or actual_sheet not in sheet_matrices:
                continue

            matrix = sheet_matrices[actual_sheet]

            if st.has_serial_column:
                if self._check_serial_column(matrix, st.data_start_row, st.col_start):
                    total_score += 5.0
            else:
                if not self._check_serial_column(matrix, st.data_start_row, st.col_start):
                    total_score += 5.0

            actual_multi_row = len(st.header_rows) > 1
            if st.is_multi_row_header == actual_multi_row:
                total_score += 5.0

            if st.has_metadata_header:
                if self._check_metadata_header(matrix, st.header_rows[0] if st.header_rows else 0):
                    total_score += 5.0
            else:
                if not self._check_metadata_header(matrix, st.header_rows[0] if st.header_rows else 0):
                    total_score += 5.0

            if st.has_summary_rows:
                if self._check_summary_rows(matrix):
                    total_score += 5.0
            else:
                if not self._check_summary_rows(matrix):
                    total_score += 5.0

            break

        return total_score

    def _extract_header_columns(
        self, matrix: list, header_rows: List[int], col_start: int, col_end: int,
    ) -> List[str]:
        if not matrix or not header_rows:
            return []
        num_rows = len(matrix)
        valid_rows = [r for r in header_rows if 0 <= r < num_rows]
        if not valid_rows:
            return []

        if len(valid_rows) == 1:
            row = valid_rows[0]
            num_cols = len(matrix[row]) if row < len(matrix) else 0
            end = min(col_end + 1, num_cols)
            return [
                str(matrix[row][c]).strip() if matrix[row][c] is not None else ""
                for c in range(col_start, end)
            ]

        end = min(col_end + 1, max(len(matrix[r]) for r in valid_rows))
        columns = []
        for c in range(col_start, end):
            parts = []
            for r in valid_rows:
                if r < len(matrix) and c < len(matrix[r]):
                    v = matrix[r][c]
                    if v is not None:
                        s = str(v).strip()
                        if s and s not in parts:
                            parts.append(s)
            columns.append("_".join(parts) if parts else "")
        return columns

    def _infer_column_types(
        self, matrix: list, data_start: int, col_start: int, col_end: int,
    ) -> Dict[str, str]:
        types = {}
        sample_rows = min(10, len(matrix) - data_start)
        for c in range(col_start, min(col_end + 1, len(matrix[0]) if matrix else 0)):
            numeric_count = 0
            string_count = 0
            for r in range(data_start, data_start + sample_rows):
                if r >= len(matrix) or c >= len(matrix[r]):
                    continue
                v = matrix[r][c]
                if v is None:
                    continue
                try:
                    float(v)
                    numeric_count += 1
                except (ValueError, TypeError):
                    string_count += 1
            col_key = f"col_{c}"
            if numeric_count > string_count:
                types[col_key] = "numeric"
            elif string_count > 0:
                types[col_key] = "string"
            else:
                types[col_key] = "mixed"
        return types

    def _check_serial_column(self, matrix: list, data_start: int, col: int) -> bool:
        sequential = 0
        for r in range(data_start, min(data_start + 10, len(matrix))):
            if r >= len(matrix) or col >= len(matrix[r]):
                continue
            v = matrix[r][col]
            if v is None:
                continue
            try:
                num = int(float(v))
                if num == sequential + 1:
                    sequential += 1
            except (ValueError, TypeError):
                pass
        return sequential >= 3

    def _check_metadata_header(self, matrix: list, first_header_row: int) -> bool:
        colon_pattern = re.compile(r'.+\s*[:]\s*.+')
        metadata_count = 0
        for r in range(0, min(first_header_row, len(matrix))):
            row = matrix[r]
            for v in row:
                if v is not None and colon_pattern.match(str(v)):
                    metadata_count += 1
                    break
        return metadata_count >= 2

    def _check_summary_rows(self, matrix: list) -> bool:
        summary_keywords = {'total', 'toplam', 'grand total', 'genel toplam', 'subtotal'}
        for r in range(max(0, len(matrix) - 10), len(matrix)):
            row = matrix[r]
            for v in row:
                if v is not None and str(v).strip().lower() in summary_keywords:
                    return True
        return False
