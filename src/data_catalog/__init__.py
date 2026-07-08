"""Flexible Excel schema & SQL catalog (slice 1: read side).

Public surface:
  get_schema_catalog()  — read API over structured Excel tables
  plan_sql(query, corpus) — existence-gated SQL planner
  map_columns_to_concepts / ColumnMapping — concept mapper
  ExcelTableMetadata — per-sheet flexible schema record
"""

from .column_mapping import (CONCEPT_ALIASES, ColumnMapping, detect_table_kind,
                             map_columns_to_concepts)
from .excel_metadata import ExcelTableMetadata
from .schema_catalog import SchemaCatalog, get_schema_catalog
from .table_resolver import SQLPlan, plan_sql

__all__ = [
    "get_schema_catalog", "SchemaCatalog", "plan_sql", "SQLPlan",
    "map_columns_to_concepts", "ColumnMapping", "detect_table_kind",
    "ExcelTableMetadata", "CONCEPT_ALIASES",
]
