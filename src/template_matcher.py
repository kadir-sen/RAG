"""
Template Matcher for Excel table extraction.

Matches incoming Excel files against stored templates using a 3-stage
scoring funnel (cheap to expensive):
  Stage 1: File-level pre-filter (filename, sheet names)     → 0-30 pts
  Stage 2: Column fingerprint (header similarity)            → 0-50 pts
  Stage 3: Structural markers (metadata, serial col, etc.)   → 0-20 pts

Total: 0-100. Files scoring above confidence_threshold are auto-matched.
"""
import re
from pathlib import Path
from typing import List, Optional, Tuple, Dict

from .template_store import FileTemplate, SheetTemplate, TemplateStore
from .config import TEMPLATE_CONFIDENCE_THRESHOLD, TEMPLATE_REVIEW_THRESHOLD
from .logger import logger


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
    """Normalize a column name for comparison (lowercase, strip, collapse spaces)."""
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
    # Try exact match first
    if pattern.lower() == actual.lower():
        return True
    # Try regex match
    try:
        return bool(re.search(pattern, actual, re.IGNORECASE))
    except re.error:
        return False


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

        Args:
            file_path: Path to the Excel file.
            sheet_names: List of sheet names in the workbook.
            sheet_matrices: Optional dict of sheet_name -> matrix (for stage 2-3).
                           If not provided, only stage 1 scoring is used.

        Returns:
            (template, score) tuple if a match is found above review threshold,
            None otherwise.
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
        """Check if the score is high enough for automatic application."""
        return score >= template.confidence_threshold * 100

    def find_sheet_template(
        self, template: FileTemplate, sheet_name: str
    ) -> Optional[SheetTemplate]:
        """Find the matching SheetTemplate for a given sheet name."""
        for pattern, st in template.sheet_templates.items():
            if _sheet_name_matches(pattern, sheet_name):
                return st
        return None

    # ── Scoring ─────────────────────────────────────────────────

    def _score_template(
        self,
        template: FileTemplate,
        file_path: str,
        sheet_names: List[str],
        sheet_matrices: Optional[Dict[str, list]],
    ) -> float:
        """
        Score a template against a file. Returns 0-100.
        """
        score = 0.0

        # Stage 1: File-level pre-filter (0-30)
        s1 = self._score_file_level(template, file_path, sheet_names)
        score += s1

        # Early exit if file-level score is too low
        if s1 < 5:
            return score

        # Stage 2: Column fingerprint (0-50) - requires matrices
        if sheet_matrices:
            s2 = self._score_column_fingerprint(template, sheet_names, sheet_matrices)
            score += s2

        # Stage 3: Structural markers (0-20) - requires matrices
        if sheet_matrices:
            s3 = self._score_structural_markers(template, sheet_names, sheet_matrices)
            score += s3

        return score

    def _score_file_level(
        self,
        template: FileTemplate,
        file_path: str,
        sheet_names: List[str],
    ) -> float:
        """
        Stage 1: File-level pre-filter.
        - Filename regex match (0-15)
        - Sheet name Jaccard similarity (0-15)
        """
        score = 0.0
        filename = Path(file_path).name

        # Filename pattern match (0-15)
        if template.file_name_pattern:
            try:
                if re.search(template.file_name_pattern, filename, re.IGNORECASE):
                    score += 15.0
            except re.error:
                pass

        # Sheet name similarity (0-15)
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
        self,
        template: FileTemplate,
        sheet_names: List[str],
        sheet_matrices: Dict[str, list],
    ) -> float:
        """
        Stage 2: Column fingerprint comparison.
        For each matched sheet, compare column names.
        - Column name Jaccard similarity (0-35)
        - Column count tolerance (0-10)
        - Column type distribution (0-5)
        """
        if not template.sheet_templates:
            return 0.0

        total_score = 0.0
        matched_sheets = 0

        for pattern, st in template.sheet_templates.items():
            # Find corresponding actual sheet
            actual_sheet = None
            for sn in sheet_names:
                if _sheet_name_matches(pattern, sn):
                    actual_sheet = sn
                    break

            if not actual_sheet or actual_sheet not in sheet_matrices:
                continue

            matrix = sheet_matrices[actual_sheet]
            matched_sheets += 1

            # Extract header columns from the matrix at the template's header rows
            actual_cols = self._extract_header_columns(matrix, st.header_rows, st.col_start, st.col_end)

            # Jaccard similarity on column names (0-35)
            template_col_set = {_normalize_col_name(c) for c in st.column_names if c}
            actual_col_set = {_normalize_col_name(c) for c in actual_cols if c}
            jaccard = _jaccard_similarity(template_col_set, actual_col_set)
            total_score += jaccard * 35.0

            # Column count tolerance (0-10)
            if st.column_count > 0:
                diff = abs(len(actual_cols) - st.column_count)
                if diff == 0:
                    total_score += 10.0
                elif diff <= 3:
                    total_score += 10.0 * (1.0 - diff / 4.0)

            # Column type distribution (0-5)
            if st.column_types and actual_cols:
                actual_types = self._infer_column_types(matrix, st.data_start_row, st.col_start, st.col_end)
                template_numeric_ratio = sum(
                    1 for t in st.column_types.values() if t == "numeric"
                ) / max(len(st.column_types), 1)
                actual_numeric_ratio = sum(
                    1 for t in actual_types.values() if t == "numeric"
                ) / max(len(actual_types), 1)
                type_similarity = 1.0 - abs(template_numeric_ratio - actual_numeric_ratio)
                total_score += type_similarity * 5.0

            break  # Score based on first matched sheet

        if matched_sheets == 0:
            return 0.0

        return total_score

    def _score_structural_markers(
        self,
        template: FileTemplate,
        sheet_names: List[str],
        sheet_matrices: Dict[str, list],
    ) -> float:
        """
        Stage 3: Structural marker validation.
        - Has metadata header (0-5)
        - Has serial column (0-5)
        - Multi-row header (0-5)
        - Summary rows (0-5)
        """
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

            # Has serial column (0-5)
            if st.has_serial_column:
                if self._check_serial_column(matrix, st.data_start_row, st.col_start):
                    total_score += 5.0
            else:
                if not self._check_serial_column(matrix, st.data_start_row, st.col_start):
                    total_score += 5.0

            # Multi-row header (0-5)
            actual_multi_row = len(st.header_rows) > 1
            if st.is_multi_row_header == actual_multi_row:
                total_score += 5.0

            # Has metadata header (0-5)
            if st.has_metadata_header:
                if self._check_metadata_header(matrix, st.header_rows[0] if st.header_rows else 0):
                    total_score += 5.0
            else:
                if not self._check_metadata_header(matrix, st.header_rows[0] if st.header_rows else 0):
                    total_score += 5.0

            # Summary rows (0-5) - simple heuristic check
            if st.has_summary_rows:
                if self._check_summary_rows(matrix):
                    total_score += 5.0
            else:
                if not self._check_summary_rows(matrix):
                    total_score += 5.0

            break  # Score based on first matched sheet

        return total_score

    # ── Helper Methods ──────────────────────────────────────────

    def _extract_header_columns(
        self,
        matrix: list,
        header_rows: List[int],
        col_start: int,
        col_end: int,
    ) -> List[str]:
        """Extract column names from matrix at the given header rows."""
        if not matrix or not header_rows:
            return []

        num_rows = len(matrix)
        valid_rows = [r for r in header_rows if 0 <= r < num_rows]
        if not valid_rows:
            return []

        # Use last header row for single-row headers
        if len(valid_rows) == 1:
            row = valid_rows[0]
            num_cols = len(matrix[row]) if row < len(matrix) else 0
            end = min(col_end + 1, num_cols)
            return [
                str(matrix[row][c]).strip() if matrix[row][c] is not None else ""
                for c in range(col_start, end)
            ]

        # Multi-row: concatenate non-empty values from each header row
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
        self,
        matrix: list,
        data_start: int,
        col_start: int,
        col_end: int,
    ) -> Dict[str, str]:
        """Infer column types from first few data rows."""
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
        """Check if the given column looks like a serial number column."""
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
        """Check if rows above the header contain label:value metadata."""
        import re
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
        """Check if the matrix contains summary/total rows near the bottom."""
        summary_keywords = {'total', 'toplam', 'grand total', 'genel toplam', 'subtotal'}

        for r in range(max(0, len(matrix) - 10), len(matrix)):
            row = matrix[r]
            for v in row:
                if v is not None and str(v).strip().lower() in summary_keywords:
                    return True

        return False
