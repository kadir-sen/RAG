"""data_catalog: concept mapper, schema catalog, and the existence-gated planner."""

import pytest

from src.data_catalog.column_mapping import (map_columns_to_concepts,
                                             detect_table_kind)


class TestConceptMapper:
    @pytest.mark.parametrize("cols,expected", [
        (["Plant", "Hrs", "Zone", "Date"],
         {"Plant": "equipment_name", "Hrs": "hours", "Zone": "block", "Date": "date"}),
        (["Equipment", "Operating Hours", "Block", "Date", "Level"],
         {"Equipment": "equipment_name", "Operating Hours": "hours",
          "Block": "block", "Date": "date", "Level": "floor"}),
        (["Trade", "Manpower Count"],
         {"Trade": "trade", "Manpower Count": "workers"}),
        (["IPC Amount", "Cumulative %", "Activity Code", "Unit Rate"],
         {"IPC Amount": "amount", "Cumulative %": "cumulative_pct",
          "Activity Code": "activity_code", "Unit Rate": "unit_rate"}),
        (["Estimated Machinery Hours"], {"Estimated Machinery Hours": "hours"}),
    ])
    def test_english_variants_map(self, cols, expected):
        got = {m.raw_column: m.canonical_concept
               for m in map_columns_to_concepts("t", cols)}
        for raw, concept in expected.items():
            assert got.get(raw) == concept, f"{raw} → {got.get(raw)} != {concept}"

    def test_junk_stays_unmapped(self):
        ms = map_columns_to_concepts("t", ["col_0", "notes", "ref", "xyz"])
        assert all(m.canonical_concept is None for m in ms)

    def test_kind_detection(self):
        eq = map_columns_to_concepts("t", ["Plant", "Hrs", "Block", "Date"])
        assert detect_table_kind(eq) == "equipment"
        mp = map_columns_to_concepts("t", ["Trade", "Headcount", "Date"])
        assert detect_table_kind(mp) == "manpower"

    def test_conflict_one_winner_per_concept(self):
        ms = map_columns_to_concepts("t", ["Equipment", "Plant", "Hrs"])
        eq = [m for m in ms if m.canonical_concept == "equipment_name"]
        assert len(eq) == 1  # only the best of Equipment/Plant wins the concept


class TestSqlFailureTaxonomy:
    @pytest.mark.parametrize("msg,expected", [
        ("LLM call failed (gemini): 429 You exceeded your quota",
         "SQL_GENERATION_LLM_UNAVAILABLE"),
        ("Binder Error: Referenced column \"Blok\" not found",
         "DUCKDB_EXECUTION_ERROR"),
        ("Catalog Error: Table with name t_x does not exist",
         "DUCKDB_EXECUTION_ERROR"),
        ("some unexpected thing", "UNKNOWN"),
    ])
    def test_classify(self, msg, expected):
        from src.data_analyzer_sql import classify_sql_failure
        assert classify_sql_failure(Exception(msg)) == expected

    def test_budget_not_classified_here(self):
        # budget/quota is re-raised upstream (402), never a SQL failure reason
        from src.data_analyzer_sql import classify_sql_failure, SqlFailureReason
        assert SqlFailureReason.NO_COMPATIBLE_TABLE == "NO_COMPATIBLE_TABLE"


class TestPlannerExistenceGate:
    """The planner must not commit to DATA when no compatible table exists."""

    def _fake_catalog(self, monkeypatch, tables):
        import src.data_catalog.table_resolver as tr

        class _Cat:
            def list_tables(self, corpus_id=None, **k):
                return tables
            def get_compatible_tables(self, concepts, corpus_id=None, min_coverage=0.75):
                out = [t for t in tables
                       if sum(1 for c in concepts if t.has_concept(c)) / len(concepts) >= min_coverage]
                return out
        monkeypatch.setattr(tr, "get_schema_catalog", lambda: _Cat())

    def _tbl(self, concepts, kind="equipment", status="confident"):
        from src.data_catalog.excel_metadata import ExcelTableMetadata
        from src.data_catalog.column_mapping import ColumnMapping
        m = ExcelTableMetadata(
            table_id="x", duckdb_table_name="t_x", source_file_name="x.xlsx",
            source_file_path="/x.xlsx", sheet_name="S1", parquet_path="/x.parquet",
            corpus_id="demo", row_count=100, column_count=len(concepts),
            raw_headers=list(concepts), detected_table_kind=kind, mapping_status=status)
        m.column_mappings = [ColumnMapping("x", c, c, canonical_concept=c) for c in concepts]
        return m

    def test_compatible_table_routes_deterministic(self, monkeypatch):
        self._fake_catalog(monkeypatch, [self._tbl(["equipment_name", "hours", "block", "date"])])
        from src.data_catalog import plan_sql
        p = plan_sql("Show equipment utilization by block", corpus_id="demo")
        assert p.execution_mode in ("deterministic_template", "generated_sql")
        assert "hours" in p.required_concepts

    def test_no_compatible_table_gates_to_no_data(self, monkeypatch):
        # only a cost table exists → equipment query must NOT route to DATA
        self._fake_catalog(monkeypatch, [self._tbl(["amount", "date"], kind="ipc")])
        from src.data_catalog import plan_sql
        p = plan_sql("Show equipment utilization by block", corpus_id="demo")
        assert p.execution_mode == "no_data"

    def test_preview_needs_no_llm(self, monkeypatch):
        self._fake_catalog(monkeypatch, [self._tbl(["amount", "date"])])
        from src.data_catalog import plan_sql
        p = plan_sql("Show contents of this Excel file as a table", corpus_id="demo")
        assert p.intent == "preview_table" and p.execution_mode == "raw_preview"

    def test_file_level_aggregate_is_data_not_doclist(self, monkeypatch):
        self._fake_catalog(monkeypatch, [self._tbl(["amount", "date"])])
        from src.data_catalog import plan_sql
        p = plan_sql("which file has the most entries", corpus_id="demo")
        assert p.intent == "file_level_aggregate"
        assert p.execution_mode == "deterministic_template"
