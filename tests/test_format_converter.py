"""Tests for format converter pipeline: sandbox, schemas, registry."""
import json
import pytest
import pandas as pd
from pathlib import Path

from src.converter_runtime import validate_converter_code, execute_converter_code
from src.schema_converter import (
    ColumnDef, TargetSchema, TargetSchemaRegistry, ValidationResult,
)
from src.converter_runtime import ConverterRegistry, ConverterEntry


# ── Code Sandbox Tests ────────────────────────────────────────


class TestValidateConverterCode:
    def test_valid_code(self):
        code = """
import pandas as pd

def convert(df):
    df = df.rename(columns={"old": "new"})
    return df
"""
        is_safe, error = validate_converter_code(code)
        assert is_safe is True
        assert error is None

    def test_empty_code(self):
        is_safe, error = validate_converter_code("")
        assert is_safe is False
        assert "Empty" in error

    def test_missing_convert_function(self):
        code = "x = 1 + 2"
        is_safe, error = validate_converter_code(code)
        assert is_safe is False
        assert "convert" in error

    def test_import_os_blocked(self):
        code = """
import os
def convert(df):
    return df
"""
        is_safe, error = validate_converter_code(code)
        assert is_safe is False
        assert "os" in error

    def test_import_subprocess_blocked(self):
        code = """
import subprocess
def convert(df):
    return df
"""
        is_safe, error = validate_converter_code(code)
        assert is_safe is False

    def test_eval_blocked(self):
        code = """
def convert(df):
    return eval("df")
"""
        is_safe, error = validate_converter_code(code)
        assert is_safe is False

    def test_exec_blocked(self):
        code = """
def convert(df):
    exec("pass")
    return df
"""
        is_safe, error = validate_converter_code(code)
        assert is_safe is False

    def test_open_blocked(self):
        code = """
def convert(df):
    f = open("/etc/passwd")
    return df
"""
        is_safe, error = validate_converter_code(code)
        assert is_safe is False

    def test_dunder_import_blocked(self):
        code = """
def convert(df):
    __import__("os")
    return df
"""
        is_safe, error = validate_converter_code(code)
        assert is_safe is False

    def test_allowed_imports(self):
        code = """
import pandas as pd
import numpy as np
import re
import datetime
import math

def convert(df):
    return df
"""
        is_safe, error = validate_converter_code(code)
        assert is_safe is True

    def test_disallowed_import_requests(self):
        code = """
import requests
def convert(df):
    return df
"""
        is_safe, error = validate_converter_code(code)
        assert is_safe is False


class TestExecuteConverterCode:
    def test_simple_rename(self):
        code = """
def convert(df):
    return df.rename(columns={"a": "x", "b": "y"})
"""
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        result = execute_converter_code(code, df)
        assert list(result.columns) == ["x", "y"]
        assert len(result) == 2

    def test_column_transform(self):
        code = """
import pandas as pd

def convert(df):
    df["total"] = df["a"] + df["b"]
    return df[["total"]]
"""
        df = pd.DataFrame({"a": [1, 2, 3], "b": [10, 20, 30]})
        result = execute_converter_code(code, df)
        assert list(result.columns) == ["total"]
        assert result["total"].tolist() == [11, 22, 33]

    def test_input_df_not_modified(self):
        code = """
def convert(df):
    df["new_col"] = 1
    return df
"""
        df = pd.DataFrame({"a": [1, 2]})
        original_cols = list(df.columns)
        execute_converter_code(code, df)
        assert list(df.columns) == original_cols

    def test_non_dataframe_return_raises(self):
        code = """
def convert(df):
    return "not a dataframe"
"""
        df = pd.DataFrame({"a": [1]})
        with pytest.raises(RuntimeError, match="pd.DataFrame"):
            execute_converter_code(code, df)

    def test_unsafe_code_rejected(self):
        code = """
import os
def convert(df):
    return df
"""
        df = pd.DataFrame({"a": [1]})
        with pytest.raises(ValueError, match="Unsafe"):
            execute_converter_code(code, df)

    def test_timeout(self):
        code = """
import time
def convert(df):
    time.sleep(10)
    return df
"""
        # time is not in allowed modules so this should fail validation
        df = pd.DataFrame({"a": [1]})
        with pytest.raises(ValueError, match="Disallowed import"):
            execute_converter_code(code, df)

    def test_runtime_error(self):
        code = """
def convert(df):
    return df["nonexistent_column"]
"""
        df = pd.DataFrame({"a": [1]})
        with pytest.raises(RuntimeError, match="Execution error"):
            execute_converter_code(code, df)


# ── Target Schema Tests ──────────────────────────────────────


class TestTargetSchema:
    def test_validate_matching_df(self):
        schema = TargetSchema(
            schema_id="test",
            name="Test Schema",
            description="Test",
            columns=[
                ColumnDef(name="date", dtype="date", required=True),
                ColumnDef(name="value", dtype="float", required=True),
            ],
        )
        df = pd.DataFrame({"date": ["2026-01-01"], "value": [100.0]})
        result = schema.validate(df)
        assert result.valid is True
        assert result.matched_columns == 2

    def test_validate_missing_required(self):
        schema = TargetSchema(
            schema_id="test",
            name="Test",
            description="",
            columns=[
                ColumnDef(name="date", dtype="date", required=True),
                ColumnDef(name="value", dtype="float", required=True),
            ],
        )
        df = pd.DataFrame({"date": ["2026-01-01"]})
        result = schema.validate(df)
        assert result.valid is False
        assert len(result.errors) == 1
        assert "value" in result.errors[0]

    def test_validate_alias_match(self):
        schema = TargetSchema(
            schema_id="test",
            name="Test",
            description="",
            columns=[
                ColumnDef(name="contractor", dtype="string", required=True, aliases=["company", "firm"]),
            ],
        )
        df = pd.DataFrame({"company": ["ABC Corp"]})
        result = schema.validate(df)
        assert result.valid is True

    def test_validate_optional_columns(self):
        schema = TargetSchema(
            schema_id="test",
            name="Test",
            description="",
            columns=[
                ColumnDef(name="date", dtype="date", required=True),
                ColumnDef(name="notes", dtype="string", required=False),
            ],
        )
        df = pd.DataFrame({"date": ["2026-01-01"]})
        result = schema.validate(df)
        assert result.valid is True

    def test_to_prompt_description(self):
        schema = TargetSchema(
            schema_id="dpr",
            name="Daily Progress Report",
            description="Daily manpower report",
            columns=[
                ColumnDef(name="date", dtype="date", required=True, description="Report date"),
            ],
        )
        desc = schema.to_prompt_description()
        assert "Daily Progress Report" in desc
        assert "date" in desc
        assert "REQUIRED" in desc


class TestTargetSchemaRegistry:
    def test_empty_registry(self, tmp_path):
        registry = TargetSchemaRegistry(schemas_dir=tmp_path / "schemas")
        assert len(registry.list_schemas()) == 0

    def test_register_and_retrieve(self, tmp_path):
        registry = TargetSchemaRegistry(schemas_dir=tmp_path / "schemas")
        schema = TargetSchema(
            schema_id="test",
            name="Test Schema",
            description="A test schema",
            columns=[ColumnDef(name="col1", dtype="string")],
        )
        registry.register_schema(schema)

        assert len(registry.list_schemas()) == 1
        retrieved = registry.get_schema("test")
        assert retrieved is not None
        assert retrieved.name == "Test Schema"

    def test_persistence(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        registry1 = TargetSchemaRegistry(schemas_dir=schemas_dir)
        registry1.register_schema(TargetSchema(
            schema_id="persist",
            name="Persistent",
            description="Test persistence",
            columns=[ColumnDef(name="a", dtype="int")],
        ))

        # New instance should load from disk
        registry2 = TargetSchemaRegistry(schemas_dir=schemas_dir)
        assert len(registry2.list_schemas()) == 1
        assert registry2.get_schema("persist").name == "Persistent"

    def test_remove_schema(self, tmp_path):
        registry = TargetSchemaRegistry(schemas_dir=tmp_path / "schemas")
        registry.register_schema(TargetSchema(
            schema_id="temp",
            name="Temporary",
            description="",
            columns=[],
        ))
        assert len(registry.list_schemas()) == 1
        registry.remove_schema("temp")
        assert len(registry.list_schemas()) == 0

    def test_get_all_descriptions(self, tmp_path):
        registry = TargetSchemaRegistry(schemas_dir=tmp_path / "schemas")
        assert registry.get_all_descriptions() == "No target schemas defined."

        registry.register_schema(TargetSchema(
            schema_id="s1",
            name="Schema One",
            description="First",
            columns=[ColumnDef(name="x", dtype="int")],
        ))
        desc = registry.get_all_descriptions()
        assert "Schema One" in desc


# ── Converter Registry Tests ─────────────────────────────────


class TestConverterRegistry:
    def test_empty_registry(self, tmp_path):
        registry = ConverterRegistry(registry_path=tmp_path / "registry.json")
        assert len(registry.list_converters()) == 0

    def test_register_converter(self, tmp_path):
        registry = ConverterRegistry(registry_path=tmp_path / "registry.json")
        cid = registry.register_converter(
            company_id="test_co",
            company_name="Test Company",
            target_schema="dpr",
            converter_code="def convert(df): return df",
            sample_file="test.xlsx",
            column_fingerprint=["date", "value"],
            test_passed=True,
        )
        assert cid.startswith("conv_")
        assert registry.has_active_converter("test_co")

    def test_get_active_converter(self, tmp_path):
        registry = ConverterRegistry(registry_path=tmp_path / "registry.json")
        registry.register_converter(
            company_id="test_co",
            company_name="Test Company",
            target_schema="dpr",
            converter_code="def convert(df): return df",
            test_passed=True,
        )
        entry = registry.get_active_converter("test_co")
        assert entry is not None
        assert entry.company_name == "Test Company"
        assert entry.target_schema == "dpr"

    def test_persistence(self, tmp_path):
        reg_path = tmp_path / "registry.json"
        reg1 = ConverterRegistry(registry_path=reg_path)
        reg1.register_converter(
            company_id="co1",
            company_name="Company 1",
            target_schema="dpr",
            converter_code="def convert(df): return df",
        )

        reg2 = ConverterRegistry(registry_path=reg_path)
        assert len(reg2.list_converters()) == 1

    def test_remove_converter(self, tmp_path):
        registry = ConverterRegistry(registry_path=tmp_path / "registry.json")
        cid = registry.register_converter(
            company_id="rm_co",
            company_name="Remove Me",
            target_schema="dpr",
            converter_code="def convert(df): return df",
        )
        assert len(registry.list_converters()) == 1
        registry.remove_converter(cid)
        assert len(registry.list_converters()) == 0

    def test_version_bump(self, tmp_path):
        registry = ConverterRegistry(registry_path=tmp_path / "registry.json")
        registry.register_converter(
            company_id="v_co",
            company_name="Versioned",
            target_schema="dpr",
            converter_code="def convert(df): return df",
        )
        entry1 = registry.get_active_converter("v_co")
        assert entry1.version == 1

        registry.register_converter(
            company_id="v_co",
            company_name="Versioned",
            target_schema="dpr",
            converter_code="def convert(df): return df.head()",
        )
        entry2 = registry.get_active_converter("v_co")
        assert entry2.version == 2

    def test_match_company_by_columns(self, tmp_path):
        registry = ConverterRegistry(registry_path=tmp_path / "registry.json")
        registry.register_converter(
            company_id="col_co",
            company_name="Column Match",
            target_schema="dpr",
            converter_code="def convert(df): return df",
            column_fingerprint=["date", "contractor", "headcount"],
        )
        # 3/3 columns match -> should match
        match = registry.match_company(
            "any_file.xlsx",
            df_columns=["date", "contractor", "headcount", "extra"],
        )
        assert match == "col_co"

    def test_match_company_by_filename(self, tmp_path):
        registry = ConverterRegistry(registry_path=tmp_path / "registry.json")
        registry.register_converter(
            company_id="fn_co",
            company_name="Filename Match",
            target_schema="dpr",
            converter_code="def convert(df): return df",
            file_name_patterns=[r"tci.*report"],
        )
        match = registry.match_company("TCI_Monthly_Report_Jan.xlsx")
        assert match == "fn_co"

    def test_no_match(self, tmp_path):
        registry = ConverterRegistry(registry_path=tmp_path / "registry.json")
        registry.register_converter(
            company_id="x_co",
            company_name="X Company",
            target_schema="dpr",
            converter_code="def convert(df): return df",
            file_name_patterns=[r"specific_pattern"],
            column_fingerprint=["very_specific_col"],
        )
        match = registry.match_company("random_file.xlsx", df_columns=["a", "b"])
        assert match is None

    def test_clear_all(self, tmp_path):
        registry = ConverterRegistry(registry_path=tmp_path / "registry.json")
        registry.register_converter(
            company_id="c1", company_name="C1",
            target_schema="dpr", converter_code="def convert(df): return df",
        )
        registry.register_converter(
            company_id="c2", company_name="C2",
            target_schema="dpr", converter_code="def convert(df): return df",
        )
        assert len(registry.list_converters()) == 2
        registry.clear_all()
        assert len(registry.list_converters()) == 0
