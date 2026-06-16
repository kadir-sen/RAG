"""Junk-table filtering — is_reliable_sql_table (no network/LLM).

Prose PDFs get table-extracted into junk OCR pseudo-tables (fragmented columns,
no schema). Those must be excluded from SQL candidacy so the planner/router route
document sub-questions to DOCUMENT, not SQL.
"""
import pytest

from src.data_analyzer_sql import is_reliable_sql_table


class TestReliableSqlTable:
    @pytest.mark.parametrize("info", [
        {"source_type": "excel", "header_metadata": {"target_schema": "equipment_log"},
         "columns": ["Date", "Machinery Name", "Estimated Machinery Hours"]},
        {"source_type": "csv", "columns": ["Block", "Workers"]},
        {"is_combined": True},
        {"is_grouped": True},
        {"is_normalized": True},
        {"source_type": "parquet", "columns": ["A", "B"]},
        {},  # unknown shape → don't exclude
    ])
    def test_reliable(self, info):
        assert is_reliable_sql_table(info) is True

    @pytest.mark.parametrize("info", [
        # CCTV-style prose-PDF junk: ocr + fragmented columns + no schema
        {"source_type": "pdf", "extraction_method": "ocr", "header_metadata": {},
         "columns": ["response_to_delay_n", "otification", "date_26_0"]},
        # PDF block-detect, no schema
        {"source_type": "pdf", "extraction_method": "block_detect",
         "columns": ["col_0", "col_1", "col_2"]},
        # Mostly-generic columns regardless of source
        {"source_type": "", "columns": ["col_0", "col_1", "col_2", "col_3"]},
        {"columns": ["Unnamed: 0", "col_1"]},
    ])
    def test_junk(self, info):
        assert is_reliable_sql_table(info) is False

    def test_pdf_with_schema_is_kept(self):
        # A PDF table that DID match a schema is trustworthy.
        info = {"source_type": "pdf", "extraction_method": "ocr",
                "header_metadata": {"target_schema": "ipc_sample"},
                "columns": ["Activity Code", "Total BOQ Amount"]}
        assert is_reliable_sql_table(info) is True
