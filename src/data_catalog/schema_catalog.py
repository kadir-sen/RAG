"""Schema Catalog service — the read API over structured Excel data.

Derives ExcelTableMetadata from the existing catalog (raw headers persisted in
``TableMetadata.columns``) + the concept mapper, and answers the questions the
SQL planner / DATA existence-gate / preview need. Corpus-scoped (project seam
nullable). No LLM.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .column_mapping import (ColumnMapping, detect_table_kind,
                             map_columns_to_concepts)
from .excel_metadata import ExcelTableMetadata, is_data_source_type

logger = logging.getLogger(__name__)

# schema_id → required concepts (used to grade confidence for a canonical kind)
_SCHEMA_CONCEPTS = {
    "equipment_log": ["equipment_name", "hours", "block", "date"],
    "manpower_production": ["trade", "workers", "block", "date"],
    "ipc_sample": ["activity_code", "amount", "boq_qty", "unit_rate"],
}


class SchemaCatalog:
    def __init__(self):
        self._mapping_overrides = self._load_overrides()

    # ── metadata build ───────────────────────────────────────
    def _build_metadata(self, tm) -> ExcelTableMetadata:
        raw_headers = [c for c in (tm.columns or []) if c != "_sheet_name"]
        target_schema = (tm.header_metadata or {}).get("target_schema")
        mappings = map_columns_to_concepts(tm.table_id, raw_headers)
        mappings = self._apply_overrides(tm.table_id, mappings)
        kind = detect_table_kind(mappings)

        mapped = {m.canonical_concept for m in mappings if m.canonical_concept}
        needs_confirm = any(m.requires_confirmation for m in mappings)
        # confidence = coverage of the best-matching schema's required concepts
        best_cov = 0.0
        for req in _SCHEMA_CONCEPTS.values():
            cov = sum(1 for c in req if c in mapped) / len(req)
            best_cov = max(best_cov, cov)
        if target_schema:
            status = "confident"
        elif best_cov >= 0.7 and not needs_confirm:
            status = "confident"
        elif mapped and (needs_confirm or best_cov >= 0.4):
            status = "needs_confirmation"
        else:
            status = "raw_only"

        return ExcelTableMetadata(
            table_id=tm.table_id,
            duckdb_table_name=tm.table_name,
            source_file_name=(tm.header_metadata or {}).get("source_file")
                              or _basename(tm.source_file),
            source_file_path=tm.source_file,
            sheet_name=tm.sheet_name,
            parquet_path=tm.parquet_path,
            corpus_id=getattr(tm, "corpus", "demo"),
            row_count=tm.row_count,
            column_count=tm.column_count,
            raw_headers=raw_headers,
            normalized_headers=[m.normalized_column for m in mappings],
            column_mappings=mappings,
            detected_table_kind=kind,
            target_schema=target_schema,
            schema_confidence=round(best_cov, 3),
            mapping_status=status,
        )

    # ── public API ───────────────────────────────────────────
    def list_tables(self, corpus_id: Optional[str] = None,
                    project_id: Optional[str] = None,
                    kind: Optional[str] = None) -> List[ExcelTableMetadata]:
        from ..catalog import get_catalog
        out: List[ExcelTableMetadata] = []
        for tm in get_catalog().get_all_tables():
            if not is_data_source_type(tm.source_type):
                continue
            if corpus_id and getattr(tm, "corpus", "demo") != corpus_id:
                continue
            meta = self._build_metadata(tm)
            if kind and meta.detected_table_kind != kind:
                continue
            out.append(meta)
        return out

    def get_table_schema(self, table_id: str,
                         with_types: bool = False) -> Optional[ExcelTableMetadata]:
        from ..catalog import get_catalog
        for tm in get_catalog().get_all_tables():
            if tm.table_id == table_id:
                meta = self._build_metadata(tm)
                if with_types:
                    self._enrich_types_and_sample(meta)
                return meta
        return None

    def get_compatible_tables(self, concepts: List[str],
                              corpus_id: Optional[str] = None,
                              min_coverage: float = 0.75
                              ) -> List[ExcelTableMetadata]:
        """Tables whose mapped concepts cover >= min_coverage of `concepts`."""
        concepts = [c for c in concepts if c]
        if not concepts:
            return []
        result = []
        for meta in self.list_tables(corpus_id=corpus_id):
            present = sum(1 for c in concepts if meta.has_concept(c))
            if present / len(concepts) >= min_coverage:
                result.append(meta)
        # richest coverage first
        result.sort(key=lambda m: -sum(1 for c in concepts if m.has_concept(c)))
        return result

    def find_tables_by_concept(self, concept: str,
                               corpus_id: Optional[str] = None
                               ) -> List[ExcelTableMetadata]:
        return [m for m in self.list_tables(corpus_id=corpus_id)
                if m.has_concept(concept)]

    def duckdb_names_for(self, table_ids: List[str],
                         corpus_id: Optional[str] = None) -> List[str]:
        """Resolve schema-catalog table_ids → physical DuckDB table names.

        The SQL planner works in table_id space; the DuckDB executor / corpus
        allow-list work in duckdb_table_name space. This is the bridge that lets
        a plan's compatible-table verdict actually bias execution. Order is
        preserved to keep the planner's richest-coverage-first ranking.
        """
        ids = list(table_ids or [])
        if not ids:
            return []
        by_id = {m.table_id: m.duckdb_table_name
                 for m in self.list_tables(corpus_id=corpus_id)}
        out: List[str] = []
        for tid in ids:
            name = by_id.get(tid)
            if name and name not in out:
                out.append(name)
        return out

    def get_low_confidence_mappings(self, corpus_id: Optional[str] = None
                                    ) -> List[Dict[str, Any]]:
        out = []
        for m in self.list_tables(corpus_id=corpus_id):
            if m.mapping_status == "needs_confirmation":
                out.append(m.to_summary())
        return out

    def get_sql_catalog_for_prompt(self, corpus_id: Optional[str] = None,
                                   candidate_tables: Optional[List[ExcelTableMetadata]] = None,
                                   max_tables: int = 12) -> str:
        from .sql_catalog_prompt import format_catalog
        tables = candidate_tables if candidate_tables is not None \
            else self.list_tables(corpus_id=corpus_id)
        return format_catalog(tables[:max_tables], corpus_id)

    # ── mapping confirmation persistence ─────────────────────
    def mark_mapping_confirmed(self, table_id: str, raw_column: str,
                               canonical_concept: str,
                               source: str = "user_confirmed") -> None:
        self._mapping_overrides.setdefault(table_id, {})[raw_column] = {
            "canonical_concept": canonical_concept, "source": source}
        self._save_overrides()

    def _apply_overrides(self, table_id: str,
                         mappings: List[ColumnMapping]) -> List[ColumnMapping]:
        ov = self._mapping_overrides.get(table_id)
        if not ov:
            return mappings
        from .column_mapping import CANONICAL_COLUMN
        for m in mappings:
            o = ov.get(m.raw_column)
            if o:
                m.canonical_concept = o["canonical_concept"]
                m.canonical_column = CANONICAL_COLUMN.get(o["canonical_concept"])
                m.confidence = 1.0
                m.source = o.get("source", "user_confirmed")
                m.requires_confirmation = False
        return mappings

    def _enrich_types_and_sample(self, meta: ExcelTableMetadata,
                                 limit: int = 10) -> None:
        """Lazy DuckDB types + sample rows (only when a caller needs them)."""
        try:
            from ..data_analyzer_sql import get_data_analyzer
            an = get_data_analyzer()
            info = an._get_table_info(meta.duckdb_table_name)
            meta.inferred_column_types = info.get("dtypes", {}) or {}
            for m in meta.column_mappings:
                m.inferred_type = meta.inferred_column_types.get(m.raw_column)
            sample = info.get("sample")
            if sample is not None:
                meta.sample_rows = sample.head(limit).to_dict("records")
        except Exception as e:
            logger.debug(f"[SchemaCatalog] type/sample enrich failed "
                         f"for {meta.table_id}: {e}")

    # ── overrides store (piggybacks schema_mappings dir) ─────
    def _overrides_path(self):
        from ..schema_profiler import _MAPPINGS_FILE
        return _MAPPINGS_FILE.parent / "column_mapping_overrides.json"

    def _load_overrides(self) -> Dict[str, Dict]:
        import json
        try:
            p = self._overrides_path()
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"[SchemaCatalog] overrides read failed: {e}")
        return {}

    def _save_overrides(self) -> None:
        import json
        try:
            p = self._overrides_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(self._mapping_overrides, indent=2,
                                    ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning(f"[SchemaCatalog] overrides save failed: {e}")


def _basename(path: str) -> str:
    from pathlib import Path
    return Path(str(path or "")).name


_CATALOG: Optional[SchemaCatalog] = None


def get_schema_catalog() -> SchemaCatalog:
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = SchemaCatalog()
    return _CATALOG
