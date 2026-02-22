"""
Unit tests for Template-Based Excel Table Extraction.

Run with: pytest tests/test_templates.py -v
"""
import pytest
import sys
import json
from pathlib import Path
from unittest.mock import patch
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── TemplateStore Tests ─────────────────────────────────────

class TestTemplateStore:
    """Tests for TemplateStore persistence and CRUD."""

    def _make_sheet_template(self, **overrides):
        from src.template_store import SheetTemplate
        defaults = dict(
            sheet_name_pattern="Sheet1",
            header_rows=[0],
            data_start_row=1,
            col_start=0,
            col_end=5,
            column_names=["a", "b", "c", "d", "e", "f"],
            column_count=6,
            column_types={"a": "string", "b": "numeric"},
            is_multi_row_header=False,
            has_metadata_header=False,
            has_serial_column=False,
            extraction_method="full_sheet",
        )
        defaults.update(overrides)
        return SheetTemplate(**defaults)

    def _make_file_template(self, tmp_path, **overrides):
        from src.template_store import FileTemplate, _generate_template_id
        st = self._make_sheet_template()
        defaults = dict(
            template_id=_generate_template_id("test", "test.xlsx"),
            name="Test Template",
            category="custom",
            file_name_pattern="test.*\\.xlsx",
            sheet_name_patterns=["Sheet1"],
            sheet_templates={"Sheet1": st},
            source_file="test.xlsx",
        )
        defaults.update(overrides)
        return FileTemplate(**defaults)

    def test_store_initialization(self, tmp_path):
        """Test store initializes with empty templates."""
        from src.template_store import TemplateStore
        store = TemplateStore(tmp_path / "templates.json")
        assert len(store.templates) == 0

    def test_add_and_retrieve_template(self, tmp_path):
        """Test adding and retrieving a template."""
        from src.template_store import TemplateStore
        store = TemplateStore(tmp_path / "templates.json")
        ft = self._make_file_template(tmp_path)

        tid = store.add_template(ft)
        assert tid == ft.template_id
        assert store.get_template(tid) is ft

    def test_persistence_roundtrip(self, tmp_path):
        """Test templates survive save/load cycle."""
        from src.template_store import TemplateStore
        path = tmp_path / "templates.json"

        # Save
        store1 = TemplateStore(path)
        ft = self._make_file_template(tmp_path)
        store1.add_template(ft)

        # Load in new instance
        store2 = TemplateStore(path)
        assert len(store2.templates) == 1

        loaded = store2.get_template(ft.template_id)
        assert loaded is not None
        assert loaded.name == "Test Template"
        assert loaded.category == "custom"
        assert len(loaded.sheet_templates) == 1

        st = loaded.sheet_templates["Sheet1"]
        assert st.column_names == ["a", "b", "c", "d", "e", "f"]
        assert st.header_rows == [0]
        assert st.data_start_row == 1

    def test_remove_template(self, tmp_path):
        """Test removing a template."""
        from src.template_store import TemplateStore
        store = TemplateStore(tmp_path / "templates.json")
        ft = self._make_file_template(tmp_path)
        store.add_template(ft)

        assert store.remove_template(ft.template_id) is True
        assert store.get_template(ft.template_id) is None
        assert len(store.templates) == 0

    def test_remove_nonexistent_returns_false(self, tmp_path):
        """Test removing nonexistent template returns False."""
        from src.template_store import TemplateStore
        store = TemplateStore(tmp_path / "templates.json")
        assert store.remove_template("tmpl_nonexistent") is False

    def test_update_template(self, tmp_path):
        """Test updating template fields increments version."""
        from src.template_store import TemplateStore
        store = TemplateStore(tmp_path / "templates.json")
        ft = self._make_file_template(tmp_path)
        store.add_template(ft)

        assert store.update_template(ft.template_id, name="Updated Name") is True
        updated = store.get_template(ft.template_id)
        assert updated.name == "Updated Name"
        assert updated.version == 2

    def test_record_match(self, tmp_path):
        """Test match_count increments."""
        from src.template_store import TemplateStore
        store = TemplateStore(tmp_path / "templates.json")
        ft = self._make_file_template(tmp_path)
        store.add_template(ft)

        store.record_match(ft.template_id)
        store.record_match(ft.template_id)
        assert store.get_template(ft.template_id).match_count == 2

    def test_list_templates(self, tmp_path):
        """Test list_templates returns sorted summary."""
        from src.template_store import TemplateStore, _generate_template_id
        store = TemplateStore(tmp_path / "templates.json")

        ft1 = self._make_file_template(tmp_path, name="Template A",
                                        template_id=_generate_template_id("a", "a.xlsx"))
        ft2 = self._make_file_template(tmp_path, name="Template B",
                                        template_id=_generate_template_id("b", "b.xlsx"))
        store.add_template(ft1)
        store.add_template(ft2)

        # ft2 gets more matches -> should be first
        store.record_match(ft2.template_id)

        listing = store.list_templates()
        assert len(listing) == 2
        assert listing[0]["name"] == "Template B"
        assert listing[0]["match_count"] == 1

    def test_validation_rejects_empty_sheets(self, tmp_path):
        """Test validation rejects template with no sheet templates."""
        from src.template_store import TemplateStore, FileTemplate
        store = TemplateStore(tmp_path / "templates.json")

        ft = FileTemplate(
            template_id="tmpl_bad",
            name="Bad Template",
            category="custom",
            file_name_pattern="",
            sheet_name_patterns=[],
            sheet_templates={},
            source_file="test.xlsx",
        )

        with pytest.raises(ValueError, match="At least one sheet template"):
            store.add_template(ft)

    def test_validation_rejects_few_columns(self, tmp_path):
        """Test validation rejects sheet with fewer than 2 columns."""
        from src.template_store import TemplateStore, FileTemplate, SheetTemplate
        store = TemplateStore(tmp_path / "templates.json")

        st = SheetTemplate(
            sheet_name_pattern="Sheet1",
            header_rows=[0],
            data_start_row=1,
            col_start=0,
            col_end=0,
            column_names=["a"],  # Only 1 column
            column_count=1,
        )

        ft = FileTemplate(
            template_id="tmpl_bad2",
            name="Bad Template 2",
            category="custom",
            file_name_pattern="",
            sheet_name_patterns=["Sheet1"],
            sheet_templates={"Sheet1": st},
            source_file="test.xlsx",
        )

        with pytest.raises(ValueError, match="needs at least 2 columns"):
            store.add_template(ft)

    def test_singleton_reset(self):
        """Test singleton can be reset for testing."""
        from src.template_store import get_template_store, reset_template_store
        reset_template_store()
        store = get_template_store()
        assert store is not None
        reset_template_store()


# ── TemplateMatcher Tests ───────────────────────────────────

class TestTemplateMatcher:
    """Tests for template matching algorithm."""

    def _make_store_with_template(self, tmp_path, **template_overrides):
        from src.template_store import (
            TemplateStore, FileTemplate, SheetTemplate, _generate_template_id,
        )
        store = TemplateStore(tmp_path / "templates.json")

        st = SheetTemplate(
            sheet_name_pattern=template_overrides.pop("sheet_pattern", "Man Power"),
            header_rows=[4, 5, 6],
            data_start_row=7,
            col_start=0,
            col_end=10,
            column_names=["s_no", "contractor", "designation", "zone_1_day", "zone_1_night",
                          "zone_2_day", "zone_2_night", "zone_3_day", "zone_3_night",
                          "total_day", "total_night"],
            column_count=11,
            column_types={"s_no": "numeric", "contractor": "string", "designation": "string",
                          "zone_1_day": "numeric", "zone_1_night": "numeric"},
            is_multi_row_header=True,
            has_metadata_header=False,
            has_serial_column=True,
            extraction_method="dense_table",
        )

        defaults = dict(
            template_id=_generate_template_id("DPR", "DPR 180207.xlsx"),
            name="DPR Manpower",
            category="dpr",
            file_name_pattern=r"DPR\s*\d{6}",
            sheet_name_patterns=["Man Power"],
            sheet_templates={"Man Power": st},
            source_file="DPR 180207.xlsx",
        )
        defaults.update(template_overrides)
        ft = FileTemplate(**defaults)
        store.add_template(ft)
        return store, ft

    def test_exact_filename_match_scores_high(self, tmp_path):
        """File matching the filename pattern scores in stage 1."""
        from src.template_matcher import TemplateMatcher

        store, ft = self._make_store_with_template(tmp_path)
        matcher = TemplateMatcher(store)

        result = matcher.find_best_template(
            "c:/data/DPR 180310.xlsx",
            ["Man Power", "Equipments"],
        )
        assert result is not None
        template, score = result
        assert template.template_id == ft.template_id
        assert score >= 20  # filename (15) + sheet name (some)

    def test_no_match_for_unrelated_file(self, tmp_path):
        """Unrelated file should not match."""
        from src.template_matcher import TemplateMatcher

        store, _ = self._make_store_with_template(tmp_path)
        matcher = TemplateMatcher(store)

        result = matcher.find_best_template(
            "c:/data/Random Report.xlsx",
            ["Summary", "Data"],
        )
        assert result is None

    def test_column_fingerprint_scoring(self, tmp_path):
        """Column names matching should boost score significantly."""
        from src.template_matcher import TemplateMatcher

        store, ft = self._make_store_with_template(tmp_path)
        matcher = TemplateMatcher(store)

        # Build a matrix that resembles the template's structure
        matrix = [[None] * 11 for _ in range(20)]
        # Header rows
        matrix[4] = ["S No", "Contractor", "Designation", "Zone 1", "Zone 1",
                      "Zone 2", "Zone 2", "Zone 3", "Zone 3", "Total", "Total"]
        matrix[5] = [None, None, None, "Day", "Night", "Day", "Night",
                     "Day", "Night", "Day", "Night"]
        matrix[6] = [None, None, None, None, None, None, None, None, None, None, None]
        # Data rows (serial numbers)
        for i in range(7, 17):
            matrix[i] = [i - 6, f"Contractor {i-6}", "Worker", 5, 3, 4, 2, 6, 1, 15, 6]

        result = matcher.find_best_template(
            "c:/data/DPR 180310.xlsx",
            ["Man Power"],
            {"Man Power": matrix},
        )
        assert result is not None
        _, score = result
        assert score >= 70  # Should have high score with column matching

    def test_is_auto_match(self, tmp_path):
        """Test auto-match threshold check."""
        from src.template_matcher import TemplateMatcher

        store, ft = self._make_store_with_template(tmp_path)
        matcher = TemplateMatcher(store)

        assert matcher.is_auto_match(ft, 90) is True
        assert matcher.is_auto_match(ft, 85) is True
        assert matcher.is_auto_match(ft, 80) is False  # below 0.85 * 100

    def test_find_sheet_template(self, tmp_path):
        """Test finding the right sheet template by name."""
        from src.template_matcher import TemplateMatcher

        store, ft = self._make_store_with_template(tmp_path)
        matcher = TemplateMatcher(store)

        st = matcher.find_sheet_template(ft, "Man Power")
        assert st is not None
        assert st.column_count == 11

        st_none = matcher.find_sheet_template(ft, "Unknown Sheet")
        assert st_none is None

    def test_sheet_name_regex_match(self, tmp_path):
        """Test sheet name matching with regex patterns."""
        from src.template_matcher import TemplateMatcher

        store, ft = self._make_store_with_template(
            tmp_path, sheet_pattern=r"CWJV.*Man\s*Power",
        )
        ft.sheet_templates = {r"CWJV.*Man\s*Power": list(ft.sheet_templates.values())[0]}
        ft.sheet_name_patterns = [r"CWJV.*Man\s*Power"]

        matcher = TemplateMatcher(store)
        st = matcher.find_sheet_template(ft, "CWJV   Man Power Report")
        assert st is not None


# ── Template Application Tests ──────────────────────────────

class TestTemplateApplication:
    """Tests for applying templates to extract tables."""

    def test_apply_simple_template(self):
        """Test applying a simple single-header template."""
        from src.excel_table_extractor import ExcelTableExtractor
        from src.template_store import SheetTemplate

        extractor = ExcelTableExtractor()

        st = SheetTemplate(
            sheet_name_pattern="Data",
            header_rows=[0],
            data_start_row=1,
            col_start=0,
            col_end=2,
            column_names=["Name", "Value", "Category"],
            column_count=3,
            is_multi_row_header=False,
            has_metadata_header=False,
            has_serial_column=False,
            extraction_method="full_sheet",
        )

        matrix = [
            ["Name", "Value", "Category"],
            ["Item A", 100, "Cat1"],
            ["Item B", 200, "Cat2"],
            ["Item C", 300, "Cat1"],
            [None, None, None],
        ]

        result = extractor._apply_sheet_template(st, matrix, "Data")
        assert result is not None
        assert len(result.df) == 3
        # _clean_dataframe normalizes column names to lowercase
        assert list(result.df.columns) == ["name", "value", "category"]
        assert result.extraction_method == "template"

    def test_apply_multirow_header_template(self):
        """Test applying a multi-row header template (DPR style)."""
        from src.excel_table_extractor import ExcelTableExtractor
        from src.template_store import SheetTemplate

        extractor = ExcelTableExtractor()

        st = SheetTemplate(
            sheet_name_pattern="Man Power",
            header_rows=[0, 1],
            data_start_row=2,
            col_start=0,
            col_end=4,
            column_names=["s_no", "contractor", "zone_1_day", "zone_1_night", "total"],
            column_count=5,
            is_multi_row_header=True,
            has_metadata_header=False,
            has_serial_column=True,
            extraction_method="dense_table",
        )

        matrix = [
            ["S No", "Contractor", "Zone 1", "Zone 1", "Total"],
            [None, None, "Day", "Night", None],
            [1, "ABC Corp", 10, 5, 15],
            [2, "XYZ Ltd", 8, 3, 11],
            [3, "DEF Inc", 12, 7, 19],
            [None, None, None, None, None],
        ]

        result = extractor._apply_sheet_template(st, matrix, "Man Power")
        assert result is not None
        assert len(result.df) == 3
        assert result.sheet_name == "Man Power"

    def test_apply_template_with_metadata(self):
        """Test template with metadata header extraction."""
        from src.excel_table_extractor import ExcelTableExtractor
        from src.template_store import SheetTemplate

        extractor = ExcelTableExtractor()

        st = SheetTemplate(
            sheet_name_pattern="Invoice",
            header_rows=[5],
            data_start_row=6,
            col_start=0,
            col_end=3,
            column_names=["sr_no", "description", "amount", "total"],
            column_count=4,
            is_multi_row_header=False,
            has_metadata_header=True,
            metadata_labels=["project_name"],
            has_serial_column=True,
            extraction_method="invoice_detect",
        )

        matrix = [
            ["Project Name : Test Project", None, None, None],
            ["Customer : ABC Corp", None, None, None],
            [None, None, None, None],
            [None, None, None, None],
            [None, None, None, None],
            ["Sr No", "Description", "Amount", "Total"],
            [1, "Item A", 100, 100],
            [2, "Item B", 200, 300],
            [None, None, None, None],
        ]

        result = extractor._apply_sheet_template(st, matrix, "Invoice")
        assert result is not None
        assert len(result.df) == 2
        assert result.header_metadata.get("project_name") == "Test Project"

    def test_apply_template_empty_data_returns_none(self):
        """Test that empty data returns None."""
        from src.excel_table_extractor import ExcelTableExtractor
        from src.template_store import SheetTemplate

        extractor = ExcelTableExtractor()

        st = SheetTemplate(
            sheet_name_pattern="Empty",
            header_rows=[0],
            data_start_row=1,
            col_start=0,
            col_end=2,
            column_names=["A", "B", "C"],
            column_count=3,
        )

        matrix = [
            ["A", "B", "C"],
            [None, None, None],
            [None, None, None],
        ]

        result = extractor._apply_sheet_template(st, matrix, "Empty")
        assert result is None


# ── Template Creation Tests ─────────────────────────────────

class TestTemplateCreation:
    """Tests for creating templates from confirmed extractions."""

    def test_create_from_simple_extraction(self):
        """Test creating template from a simple extraction result."""
        from src.excel_table_extractor import ExcelTableExtractor, ExtractedTable

        extractor = ExcelTableExtractor()

        df = pd.DataFrame({
            "name": ["A", "B", "C"],
            "value": [1, 2, 3],
            "category": ["x", "y", "z"],
        })

        table = ExtractedTable(
            df=df,
            sheet_name="Data",
            start_row=1,
            start_col=1,
            end_row=4,
            end_col=3,
            extraction_method="full_sheet",
        )

        template = extractor.create_template_from_extraction(
            tables=[table],
            file_path="c:/data/test_file.xlsx",
            sheet_names=["Data"],
            template_name="Test Template",
            category="custom",
        )

        assert template.name == "Test Template"
        assert template.category == "custom"
        assert template.template_id.startswith("tmpl_")
        assert "Data" in template.sheet_templates
        st = template.sheet_templates["Data"]
        assert st.column_count == 3
        assert "name" in st.column_names
        assert st.column_types["value"] == "numeric"
        assert st.column_types["name"] == "string"

    def test_create_preserves_serial_column_detection(self):
        """Test that serial column is detected during template creation."""
        from src.excel_table_extractor import ExcelTableExtractor, ExtractedTable

        extractor = ExcelTableExtractor()

        df = pd.DataFrame({
            "sr_no": [1, 2, 3, 4, 5],
            "item": ["A", "B", "C", "D", "E"],
            "amount": [100, 200, 300, 400, 500],
        })

        table = ExtractedTable(
            df=df,
            sheet_name="Sheet1",
            start_row=1,
            start_col=1,
            end_row=6,
            end_col=3,
            extraction_method="invoice_detect",
        )

        template = extractor.create_template_from_extraction(
            tables=[table],
            file_path="c:/data/invoice.xlsx",
            sheet_names=["Sheet1"],
            template_name="Invoice Template",
            category="invoice",
        )

        st = template.sheet_templates["Sheet1"]
        assert st.has_serial_column is True

    def test_create_from_dense_extraction(self):
        """Test template creation from dense table extraction."""
        from src.excel_table_extractor import ExcelTableExtractor, ExtractedTable

        extractor = ExcelTableExtractor()

        df = pd.DataFrame({
            "s_no": [1, 2, 3],
            "zone_1_day": [10, 20, 30],
            "zone_1_night": [5, 10, 15],
        })

        table = ExtractedTable(
            df=df,
            sheet_name="Man Power",
            start_row=5,
            start_col=1,
            end_row=8,
            end_col=3,
            extraction_method="dense_table",
        )

        template = extractor.create_template_from_extraction(
            tables=[table],
            file_path="c:/data/DPR 180207.xlsx",
            sheet_names=["Man Power"],
            template_name="DPR Template",
            category="dpr",
        )

        st = template.sheet_templates["Man Power"]
        assert st.is_multi_row_header is True
        assert st.extraction_method == "dense_table"
        assert r"\d+" in template.file_name_pattern  # numbers generalized


# ── Integration: Template Extraction Pipeline ────────────────

class TestTemplateExtraction:
    """Integration tests for the full template extraction pipeline."""

    def test_extract_tables_without_templates(self):
        """Existing extraction works when no templates exist."""
        from src.template_store import reset_template_store
        reset_template_store()

        from src.excel_table_extractor import ExcelTableExtractor

        # This should not crash even with empty template store
        extractor = ExcelTableExtractor()
        # _extract_via_template should return None with no templates
        result = extractor._extract_via_template("nonexistent.xlsx", None)
        # With no templates, should return None gracefully

    def test_template_fallback_on_no_match(self, tmp_path):
        """When template doesn't match, extraction falls through to heuristics."""
        from src.template_store import TemplateStore, FileTemplate, SheetTemplate, _generate_template_id, reset_template_store

        reset_template_store()

        # Create a store with a template that won't match
        store = TemplateStore(tmp_path / "templates.json")
        st = SheetTemplate(
            sheet_name_pattern="Very Specific Sheet",
            header_rows=[0],
            data_start_row=1,
            col_start=0,
            col_end=5,
            column_names=["a", "b", "c", "d", "e", "f"],
            column_count=6,
        )
        ft = FileTemplate(
            template_id=_generate_template_id("specific", "specific.xlsx"),
            name="Very Specific Template",
            category="custom",
            file_name_pattern="very_specific_\\d+",
            sheet_name_patterns=["Very Specific Sheet"],
            sheet_templates={"Very Specific Sheet": st},
            source_file="specific.xlsx",
        )
        store.add_template(ft)

        # When a different file comes in, template should not match
        from src.template_matcher import TemplateMatcher
        matcher = TemplateMatcher(store)
        result = matcher.find_best_template(
            "c:/data/DPR 180207.xlsx",
            ["Man Power", "Equipments"],
        )
        # Score should be below threshold (different name + different sheets)
        assert result is None
