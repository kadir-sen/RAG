"""ExcelTableMetadata — the flexible, per-sheet schema record.

Derived from the existing ``catalog.TableMetadata`` (single source of truth for
raw headers / corpus / parquet) enriched with concept mappings. Slice 1 derives
this on read without changing ingest; slice 2 persists the richer fields at
ingest time. project_id/customer_id are nullable seams (corpus-scoped for now).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .column_mapping import ColumnMapping

_DATA_SOURCE_TYPES = {"excel", "csv", "parquet", "normalized_raw",
                      "normalized_clean", "combined", "unified_schema"}


@dataclass
class ExcelTableMetadata:
    table_id: str
    duckdb_table_name: str
    source_file_name: str
    source_file_path: str
    sheet_name: Optional[str]
    parquet_path: str
    corpus_id: str
    row_count: int
    column_count: int
    raw_headers: List[str]
    normalized_headers: List[str] = field(default_factory=list)
    inferred_column_types: Dict[str, str] = field(default_factory=dict)
    sample_rows: List[Dict[str, Any]] = field(default_factory=list)
    column_mappings: List[ColumnMapping] = field(default_factory=list)
    detected_table_kind: str = "generic"
    target_schema: Optional[str] = None
    schema_confidence: float = 0.0
    mapping_status: str = "raw_only"     # confident | needs_confirmation | raw_only | failed
    project_id: Optional[str] = None     # nullable seam
    customer_id: Optional[str] = None    # nullable seam

    def mapped_concepts(self) -> Dict[str, str]:
        """concept → raw physical column (only mapped columns)."""
        return {m.canonical_concept: m.raw_column
                for m in self.column_mappings if m.canonical_concept}

    def has_concept(self, concept: str) -> bool:
        return any(m.canonical_concept == concept for m in self.column_mappings)

    def to_summary(self) -> Dict[str, Any]:
        return {
            "table_id": self.table_id,
            "duckdb_table_name": self.duckdb_table_name,
            "source_file_name": self.source_file_name,
            "sheet_name": self.sheet_name,
            "corpus_id": self.corpus_id,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "raw_headers": self.raw_headers,
            "detected_table_kind": self.detected_table_kind,
            "target_schema": self.target_schema,
            "schema_confidence": round(self.schema_confidence, 3),
            "mapping_status": self.mapping_status,
            "columns": [m.to_dict() for m in self.column_mappings],
        }


def is_data_source_type(source_type: str) -> bool:
    return str(source_type or "").lower() in _DATA_SOURCE_TYPES
