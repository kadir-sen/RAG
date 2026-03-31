"""
Format Pipeline Tests - Validates schema loading, Excel template reading,
column matching, and end-to-end conversion pipeline.

Tests split into:
1. Schema Loading (no LLM) - target schema JSON structure
2. Excel Template (no LLM) - formatlar/*.xlsx readability
3. Schema Matching (no LLM) - column alias matching logic
4. Code Sandbox (no LLM) - converter code validation/execution
5. End-to-End (requires LLM) - full conversion pipeline with real files
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import SCHEMAS_DIR
from src.schema_converter import (
    TargetSchemaRegistry,
    TargetSchema,
    ColumnDef,
    ValidationResult,
)
from src.converter_runtime import validate_converter_code, execute_converter_code
from src.converter_runtime import ConverterRegistry

# ── Paths ──────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
FORMATLAR_DIR = PROJECT_ROOT / "formatlar"
SCHEMAS_JSON_DIR = PROJECT_ROOT / "storage" / "schemas"

EXPECTED_SCHEMAS = {
    "equipment_log": {"column_count": 5, "file": "equipment_log.json"},
    "ipc_sample": {"column_count": 15, "file": "ipc_sample.json"},
    "manpower_production": {"column_count": 8, "file": "manpower_production.json"},
}

EXPECTED_TEMPLATES = [
    "Equipment Log.xlsx",
    "IPC Sample.xlsx",
    "Manpower Production Log.xlsx",
]


# ═══════════════════════════════════════════════════════════════
# 1. SCHEMA LOADING TESTS
# ═══════════════════════════════════════════════════════════════


class TestSchemaLoading:
    """Test that all target schemas exist and are well-formed."""

    def test_all_target_schemas_exist(self):
        """Three JSON schema files must exist."""
        for schema_id, info in EXPECTED_SCHEMAS.items():
            path = SCHEMAS_JSON_DIR / info["file"]
            assert path.exists(), f"Schema file missing: {path}"

    def test_schema_json_parseable(self):
        """All schema files must be valid JSON."""
        for schema_id, info in EXPECTED_SCHEMAS.items():
            path = SCHEMAS_JSON_DIR / info["file"]
            data = json.loads(path.read_text(encoding="utf-8"))
            assert "schema_id" in data
            assert "columns" in data

    def test_schema_structure(self):
        """Every column must have name, dtype, required, and aliases."""
        for schema_id, info in EXPECTED_SCHEMAS.items():
            path = SCHEMAS_JSON_DIR / info["file"]
            data = json.loads(path.read_text(encoding="utf-8"))
            for col in data["columns"]:
                assert "name" in col, f"Column missing 'name' in {schema_id}"
                assert "dtype" in col, f"Column missing 'dtype' in {schema_id}: {col['name']}"
                assert "aliases" in col, f"Column missing 'aliases' in {schema_id}: {col['name']}"
                assert isinstance(col["aliases"], list), f"aliases must be list in {schema_id}: {col['name']}"

    def test_schema_column_counts(self):
        """Verify expected column counts for each schema."""
        for schema_id, info in EXPECTED_SCHEMAS.items():
            path = SCHEMAS_JSON_DIR / info["file"]
            data = json.loads(path.read_text(encoding="utf-8"))
            actual = len(data["columns"])
            expected = info["column_count"]
            assert actual == expected, (
                f"{schema_id}: expected {expected} columns, got {actual}"
            )

    def test_schema_ids_match_filenames(self):
        """Schema ID inside JSON should match the filename (sans extension)."""
        for schema_id, info in EXPECTED_SCHEMAS.items():
            path = SCHEMAS_JSON_DIR / info["file"]
            data = json.loads(path.read_text(encoding="utf-8"))
            assert data["schema_id"] == schema_id

    def test_registry_loads_all_schemas(self):
        """TargetSchemaRegistry should load all 3 schemas."""
        registry = TargetSchemaRegistry(SCHEMAS_JSON_DIR)
        schemas = registry.list_schemas()
        schema_ids = {s["schema_id"] for s in schemas}
        for expected_id in EXPECTED_SCHEMAS:
            assert expected_id in schema_ids, f"Registry missing schema: {expected_id}"

    def test_schema_required_columns(self):
        """Equipment log: all 5 required, IPC: 6 required, Manpower: all 8 required."""
        registry = TargetSchemaRegistry(SCHEMAS_JSON_DIR)

        eq = registry.get_schema("equipment_log")
        assert eq is not None
        assert all(c.required for c in eq.columns), "All equipment_log columns should be required"

        ipc = registry.get_schema("ipc_sample")
        assert ipc is not None
        required_count = sum(1 for c in ipc.columns if c.required)
        assert required_count == 6, f"IPC should have 6 required columns, got {required_count}"

        mp = registry.get_schema("manpower_production")
        assert mp is not None
        assert all(c.required for c in mp.columns), "All manpower_production columns should be required"


# ═══════════════════════════════════════════════════════════════
# 2. EXCEL TEMPLATE TESTS
# ═══════════════════════════════════════════════════════════════


class TestExcelTemplates:
    """Test that formatlar/ Excel templates are readable and contain data."""

    def test_all_template_files_exist(self):
        """All 3 template files must exist in formatlar/."""
        for name in EXPECTED_TEMPLATES:
            path = FORMATLAR_DIR / name
            assert path.exists(), f"Template file missing: {path}"

    def test_template_readable(self):
        """Each template must be readable by pandas."""
        for name in EXPECTED_TEMPLATES:
            path = FORMATLAR_DIR / name
            df = pd.read_excel(str(path), nrows=5)
            assert df is not None, f"Could not read {name}"
            assert len(df.columns) > 0, f"No columns in {name}"

    def test_template_has_data(self):
        """Each template must have at least 1 data row."""
        for name in EXPECTED_TEMPLATES:
            path = FORMATLAR_DIR / name
            xls = pd.ExcelFile(str(path))
            total_rows = 0
            for sheet in xls.sheet_names:
                sdf = pd.read_excel(str(path), sheet_name=sheet)
                total_rows += len(sdf)
            assert total_rows > 0, f"Template {name} has no data rows"

    def test_equipment_log_columns(self):
        """Equipment Log template should have date/block/floor/machinery related columns."""
        path = FORMATLAR_DIR / "Equipment Log.xlsx"
        xls = pd.ExcelFile(str(path))
        all_cols = set()
        for sheet in xls.sheet_names:
            sdf = pd.read_excel(str(path), sheet_name=sheet, nrows=1)
            all_cols.update(c.lower().strip() for c in sdf.columns)
        # At least some recognizable columns
        assert len(all_cols) >= 3, f"Equipment Log has too few columns: {all_cols}"

    def test_manpower_production_columns(self):
        """Manpower Production template should have worker/activity related columns."""
        path = FORMATLAR_DIR / "Manpower Production Log.xlsx"
        xls = pd.ExcelFile(str(path))
        all_cols = set()
        for sheet in xls.sheet_names:
            sdf = pd.read_excel(str(path), sheet_name=sheet, nrows=1)
            all_cols.update(c.lower().strip() for c in sdf.columns)
        assert len(all_cols) >= 3, f"Manpower Production has too few columns: {all_cols}"


# ═══════════════════════════════════════════════════════════════
# 3. SCHEMA MATCHING / VALIDATION TESTS
# ═══════════════════════════════════════════════════════════════


class TestSchemaValidation:
    """Test TargetSchema.validate() logic with synthetic DataFrames."""

    def test_equipment_log_valid_df(self):
        """A DataFrame with correct columns should pass equipment_log validation."""
        registry = TargetSchemaRegistry(SCHEMAS_JSON_DIR)
        schema = registry.get_schema("equipment_log")
        assert schema is not None

        df = pd.DataFrame({
            "Date": ["2025-01-01"],
            "Block": ["A"],
            "Floor": ["1"],
            "Machinery Name": ["Crane"],
            "Estimated Machinery Hours": [8.0],
        })
        result = schema.validate(df)
        assert result.valid, f"Validation errors: {result.errors}"

    def test_equipment_log_alias_matching(self):
        """Alias columns (e.g., 'tarih' for Date) should also validate."""
        registry = TargetSchemaRegistry(SCHEMAS_JSON_DIR)
        schema = registry.get_schema("equipment_log")
        assert schema is not None

        df = pd.DataFrame({
            "date": ["2025-01-01"],
            "block": ["A"],
            "floor": ["1"],
            "machinery": ["Crane"],
            "hours": [8.0],
        })
        result = schema.validate(df)
        assert result.valid, f"Alias validation errors: {result.errors}"

    def test_missing_required_column_fails(self):
        """Missing a required column should fail validation."""
        registry = TargetSchemaRegistry(SCHEMAS_JSON_DIR)
        schema = registry.get_schema("equipment_log")
        assert schema is not None

        df = pd.DataFrame({
            "Date": ["2025-01-01"],
            "Block": ["A"],
            # Missing Floor, Machinery Name, Estimated Machinery Hours
        })
        result = schema.validate(df)
        assert not result.valid
        assert len(result.errors) == 3

    def test_ipc_required_columns_only(self):
        """IPC schema with only 6 required columns should pass."""
        registry = TargetSchemaRegistry(SCHEMAS_JSON_DIR)
        schema = registry.get_schema("ipc_sample")
        assert schema is not None

        df = pd.DataFrame({
            "Activity Code": ["A01"],
            "Activity Name": ["Earthworks"],
            "Unit": ["m3"],
            "BOQ Qty": [100.0],
            "Unit Rate": [50.0],
            "Total BOQ Amount": [5000.0],
        })
        result = schema.validate(df)
        assert result.valid, f"IPC validation errors: {result.errors}"

    def test_manpower_production_valid(self):
        """Manpower production with all 8 columns should pass."""
        registry = TargetSchemaRegistry(SCHEMAS_JSON_DIR)
        schema = registry.get_schema("manpower_production")
        assert schema is not None

        df = pd.DataFrame({
            "Date": ["2025-01-01"],
            "Block": ["A"],
            "Floor": ["Ground"],
            "Activity Description": ["Concrete pouring"],
            "Job Description": ["Mason"],
            "Number of Workers": [10],
            "Quantification": [50.0],
            "Unit of Measure": ["m3"],
        })
        result = schema.validate(df)
        assert result.valid, f"Manpower validation errors: {result.errors}"


# ═══════════════════════════════════════════════════════════════
# 4. CODE SANDBOX TESTS
# ═══════════════════════════════════════════════════════════════


class TestCodeSandbox:
    """Test converter code validation and execution."""

    def test_valid_code_passes_validation(self):
        """A proper convert function should pass validation."""
        code = """
import pandas as pd

def convert(df):
    result = df.copy()
    result.columns = [c.strip() for c in result.columns]
    return result
"""
        is_safe, error = validate_converter_code(code)
        assert is_safe, f"Should be safe: {error}"

    def test_dangerous_code_blocked(self):
        """Code with os.system should be blocked."""
        code = """
import os

def convert(df):
    os.system("rm -rf /")
    return df
"""
        is_safe, error = validate_converter_code(code)
        assert not is_safe
        assert error is not None

    def test_code_without_convert_fails(self):
        """Code without def convert() should fail."""
        code = """
import pandas as pd

def transform(df):
    return df
"""
        is_safe, error = validate_converter_code(code)
        assert not is_safe

    def test_execution_returns_dataframe(self):
        """execute_converter_code should return a DataFrame."""
        code = """
import pandas as pd

def convert(df):
    return df.rename(columns={"a": "Date", "b": "Block"})
"""
        input_df = pd.DataFrame({"a": ["2025-01-01"], "b": ["A"]})
        result = execute_converter_code(code, input_df, timeout=10)
        assert isinstance(result, pd.DataFrame)
        assert "Date" in result.columns
        assert "Block" in result.columns

    def test_execution_timeout(self):
        """Infinite loop should trigger timeout."""
        code = """
import pandas as pd

def convert(df):
    while True:
        pass
    return df
"""
        input_df = pd.DataFrame({"a": [1]})
        with pytest.raises(TimeoutError):
            execute_converter_code(code, input_df, timeout=2)


# ═══════════════════════════════════════════════════════════════
# 5. CONVERTER REGISTRY TESTS
# ═══════════════════════════════════════════════════════════════


class TestConverterRegistry:
    """Test converter registry CRUD and matching."""

    def test_register_and_retrieve(self, tmp_path):
        """Register a converter and retrieve it."""
        registry_file = tmp_path / "registry.json"
        reg = ConverterRegistry(registry_path=registry_file)

        reg.register_converter(
            company_id="test_co",
            company_name="Test Company",
            target_schema="equipment_log",
            converter_code="def convert(df): return df",
            column_fingerprint=["Date", "Block", "Floor"],
            test_passed=True,
        )

        entry = reg.get_active_converter("test_co")
        assert entry is not None
        assert entry.target_schema == "equipment_log"
        assert entry.test_passed

    def test_column_fingerprint_matching(self, tmp_path):
        """Column fingerprint matching should work at 70% threshold."""
        registry_file = tmp_path / "registry.json"
        reg = ConverterRegistry(registry_path=registry_file)

        reg.register_converter(
            company_id="test_co",
            company_name="Test Company",
            target_schema="equipment_log",
            converter_code="def convert(df): return df",
            column_fingerprint=["Date", "Block", "Floor", "Machinery", "Hours"],
            test_passed=True,
        )

        # 4 out of 5 = 80% match -> should match
        matched = reg.match_company(
            "test_file.xlsx",
            df_columns=["Date", "Block", "Floor", "Machinery"]
        )
        assert matched == "test_co"

        # 2 out of 5 = 40% match -> should NOT match
        not_matched = reg.match_company(
            "other_file.xlsx",
            df_columns=["Date", "Block", "Something", "Else"]
        )
        assert not_matched is None

    def test_clear_all(self, tmp_path):
        """clear_all should remove all converters."""
        registry_file = tmp_path / "registry.json"
        reg = ConverterRegistry(registry_path=registry_file)

        reg.register_converter(
            company_id="co1",
            company_name="Company 1",
            target_schema="equipment_log",
            converter_code="def convert(df): return df",
        )
        reg.register_converter(
            company_id="co2",
            company_name="Company 2",
            target_schema="ipc_sample",
            converter_code="def convert(df): return df",
        )

        assert len(reg.list_converters()) == 2
        reg.clear_all()
        assert len(reg.list_converters()) == 0


# ═══════════════════════════════════════════════════════════════
# 6. FORMAT CONVERTER READ TESTS (no LLM)
# ═══════════════════════════════════════════════════════════════


class TestFormatConverterReadSheets:
    """Test FormatConverter._read_sheets() with real template files."""

    def test_read_equipment_log(self):
        """FormatConverter should be able to read Equipment Log sheets."""
        from src.schema_converter import FormatConverter
        converter = FormatConverter()
        path = str(FORMATLAR_DIR / "Equipment Log.xlsx")
        sheets = converter._read_sheets(path)
        assert isinstance(sheets, dict)
        assert len(sheets) >= 1
        first_df = next(iter(sheets.values()))
        assert not first_df.empty
        assert len(first_df.columns) >= 3

    def test_read_ipc_sample(self):
        """FormatConverter should be able to read IPC Sample (multi-sheet)."""
        from src.schema_converter import FormatConverter
        converter = FormatConverter()
        path = str(FORMATLAR_DIR / "IPC Sample.xlsx")
        sheets = converter._read_sheets(path)
        assert isinstance(sheets, dict)
        assert len(sheets) >= 1
        for sheet_name, df in sheets.items():
            assert not df.empty

    def test_read_manpower_production(self):
        """FormatConverter should be able to read Manpower Production Log."""
        from src.schema_converter import FormatConverter
        converter = FormatConverter()
        path = str(FORMATLAR_DIR / "Manpower Production Log.xlsx")
        sheets = converter._read_sheets(path)
        assert isinstance(sheets, dict)
        assert len(sheets) >= 1
        first_df = next(iter(sheets.values()))
        assert not first_df.empty

    def test_read_nonexistent_returns_empty(self):
        """Non-existent file should raise an exception or return empty dict."""
        from src.schema_converter import FormatConverter
        converter = FormatConverter()
        with pytest.raises(Exception):
            converter._read_sheets("/nonexistent/file.xlsx")


# ═══════════════════════════════════════════════════════════════
# 7. CHAT CONTEXT TESTS
# ═══════════════════════════════════════════════════════════════


class TestChatContext:
    """Test format_chat_context() improvements."""

    def test_full_text_no_truncation(self):
        """Assistant messages should not be truncated at 500 chars."""
        from src.conversation_store import Message, format_chat_context

        long_text = "A" * 800
        messages = [
            Message(role="user", content="question", timestamp="2025-01-01T00:00:00"),
            Message(role="assistant", content=long_text, timestamp="2025-01-01T00:01:00"),
        ]
        context = format_chat_context(messages, max_messages=10, max_chars=12000)
        # Full text should be present (not truncated to 500)
        assert long_text in context

    def test_sql_table_info_included(self):
        """SQL query info should appear in context."""
        from src.conversation_store import Message, format_chat_context

        messages = [
            Message(
                role="assistant",
                content="Here are the results",
                timestamp="2025-01-01T00:01:00",
                sql='SELECT * FROM "equipment_data" WHERE block = \'A\'',
                query_type="data",
            ),
        ]
        context = format_chat_context(messages)
        assert "equipment_data" in context
        assert "[DATA]" in context

    def test_query_type_badge(self):
        """Query type should be shown as badge."""
        from src.conversation_store import Message, format_chat_context

        messages = [
            Message(
                role="assistant",
                content="Found 3 documents",
                timestamp="2025-01-01T00:01:00",
                query_type="document",
            ),
        ]
        context = format_chat_context(messages)
        assert "[DOCUMENT]" in context

    def test_max_chars_limit(self):
        """Total context should not exceed max_chars."""
        from src.conversation_store import Message, format_chat_context

        messages = [
            Message(role="user", content="q" * 500, timestamp="2025-01-01T00:00:00"),
            Message(role="assistant", content="a" * 500, timestamp="2025-01-01T00:01:00"),
        ] * 20  # 40 messages, way over limit

        context = format_chat_context(messages, max_messages=10, max_chars=3000)
        # Should be under limit (allowing some overhead for tags)
        assert len(context) < 4000

    def test_empty_messages(self):
        """Empty message list should return empty string."""
        from src.conversation_store import format_chat_context
        assert format_chat_context([]) == ""

    def test_extract_table_from_sql(self):
        """_extract_table_from_sql should find table names."""
        from src.conversation_store import _extract_table_from_sql

        assert _extract_table_from_sql('SELECT * FROM "my_table"') == "my_table"
        assert _extract_table_from_sql("SELECT col FROM equipment_log WHERE x=1") == "equipment_log"
        assert _extract_table_from_sql("INVALID SQL") == "unknown"


# ═══════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
