"""Compact catalog text handed to the SQL-generation LLM.

Lists ONLY real DuckDB table names and real physical column names (+ concept
hints) so the model can never invent identifiers. Table names come from the
catalog, never reconstructed by the LLM.
"""

from __future__ import annotations

from typing import List, Optional

from .excel_metadata import ExcelTableMetadata


def format_catalog(tables: List[ExcelTableMetadata],
                   corpus_id: Optional[str] = None) -> str:
    if not tables:
        return "Available structured tables: (none in this project)"
    scope = f" (corpus={corpus_id})" if corpus_id else ""
    lines = [f"Available structured tables{scope} — use these EXACT table and "
             "column names, do not invent identifiers:"]
    for t in tables:
        src = t.source_file_name + (f" / {t.sheet_name}" if t.sheet_name else "")
        lines.append(f"\nTable: {t.duckdb_table_name}   "
                     f"(kind: {t.detected_table_kind}, rows: {t.row_count:,})")
        lines.append(f"  Source: {src}")
        lines.append("  Columns:")
        for m in t.column_mappings:
            concept = m.canonical_concept or "-"
            typ = m.inferred_type or "?"
            quoted = f'"{m.raw_column}"'
            lines.append(f"   - {quoted} | concept: {concept} | type: {typ}"
                         + (f" | conf: {m.confidence:.2f}" if m.canonical_concept else ""))
    return "\n".join(lines)
