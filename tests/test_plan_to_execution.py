"""Sprint A — the SQL planner's verdict must actually reach execution.

Before this wiring, ``plan_sql`` produced a real table/column catalog but the
router used only its ``no_data`` signal and threw the rest away; the executor
then re-selected a table heuristically and generated SQL with no concept hint.
These tests lock in the seam:

  * table_id → duckdb_table_name resolution (the bridge that lets a plan bias
    which physical table the executor may choose);
  * the concept→column mapping is injected into SQL generation so the model
    uses the confirmed column instead of guessing;
  * the mapping only pins columns that actually exist in the selected table
    (a plan hint never points the model at a non-existent column).
"""

import duckdb
import pandas as pd
import pytest

from src.data_analyzer_sql import DataAnalyzerSQL
from src.data_catalog.column_mapping import ColumnMapping
from src.data_catalog.excel_metadata import ExcelTableMetadata
from src.data_catalog.schema_catalog import SchemaCatalog


def _meta(table_id, duckdb_name, concepts):
    m = ExcelTableMetadata(
        table_id=table_id, duckdb_table_name=duckdb_name,
        source_file_name=f"{table_id}.xlsx", source_file_path=f"/{table_id}.xlsx",
        sheet_name="S1", parquet_path=f"/{table_id}.parquet", corpus_id="demo",
        row_count=100, column_count=len(concepts), raw_headers=list(concepts),
        detected_table_kind="equipment", mapping_status="confident")
    m.column_mappings = [ColumnMapping(table_id, c, c, canonical_concept=c)
                         for c in concepts]
    return m


class TestTableIdBridge:
    """The planner speaks table_id; the executor speaks duckdb_table_name."""

    def _catalog(self, monkeypatch, metas):
        cat = SchemaCatalog()
        monkeypatch.setattr(cat, "list_tables", lambda corpus_id=None, **k: metas)
        return cat

    def test_resolves_ids_to_duckdb_names(self, monkeypatch):
        cat = self._catalog(monkeypatch, [
            _meta("eq1", "t_equipment", ["equipment_name", "hours", "block"]),
            _meta("cost1", "t_cost", ["amount", "date"]),
        ])
        assert cat.duckdb_names_for(["eq1"]) == ["t_equipment"]
        assert cat.duckdb_names_for(["cost1", "eq1"]) == ["t_cost", "t_equipment"]

    def test_unknown_ids_dropped(self, monkeypatch):
        cat = self._catalog(monkeypatch, [_meta("eq1", "t_equipment", ["hours"])])
        assert cat.duckdb_names_for(["ghost", "eq1"]) == ["t_equipment"]

    def test_empty_is_empty(self, monkeypatch):
        cat = self._catalog(monkeypatch, [_meta("eq1", "t_equipment", ["hours"])])
        assert cat.duckdb_names_for([]) == []
        assert cat.duckdb_names_for(None) == []


class TestConceptColumnHint:
    """The concept→column mapping must reach SQL generation, pinned to columns
    that exist in the selected table."""

    @pytest.fixture
    def analyzer(self):
        a = DataAnalyzerSQL.__new__(DataAnalyzerSQL)  # skip real __init__
        a.conn = duckdb.connect(':memory:')
        a.tables = {}
        a.file_paths = {}
        a._jargon = None
        df = pd.DataFrame({'Plant': ['Excavator', 'Crane'],
                           'Operating Hours': [8, 6],
                           'Zone': ['A', 'B']})
        a.conn.register('tmp', df)
        a.conn.execute('CREATE TABLE equipment AS SELECT * FROM tmp')
        info = a._get_table_info('equipment')
        a.tables['equipment'] = {'file_name': 'eq.xlsx', 'file_path': '/eq.xlsx',
                                 **info}
        return a

    def _capture_prompt(self, analyzer, monkeypatch, **kw):
        captured = {}

        class _Resp:
            text = "SELECT * FROM equipment"
            usage = None

        def _fake_generate_text(prompt, **_):
            captured["prompt"] = prompt
            return _Resp()

        import src.llm_client as llm_client
        monkeypatch.setattr(llm_client, "generate_text", _fake_generate_text)
        monkeypatch.setattr("src.data_analyzer_sql.get_current_trace", lambda: None,
                            raising=False)
        analyzer._generate_sql("equipment utilization by zone", "equipment", **kw)
        return captured.get("prompt", "")

    def test_hint_injected_for_existing_columns(self, analyzer, monkeypatch):
        prompt = self._capture_prompt(
            analyzer, monkeypatch,
            concept_columns={"hours": "Operating Hours", "block": "Zone"})
        assert "CONFIRMED CONCEPT" in prompt
        assert "Operating Hours" in prompt
        assert "Zone" in prompt

    def test_nonexistent_column_not_injected(self, analyzer, monkeypatch):
        # planner best-table concept points at a column not in THIS table → drop
        prompt = self._capture_prompt(
            analyzer, monkeypatch,
            concept_columns={"cost": "Total Amount"})
        assert "Total Amount" not in prompt
        assert "CONFIRMED CONCEPT" not in prompt

    def test_no_hint_without_mapping(self, analyzer, monkeypatch):
        prompt = self._capture_prompt(analyzer, monkeypatch, concept_columns=None)
        assert "CONFIRMED CONCEPT" not in prompt
