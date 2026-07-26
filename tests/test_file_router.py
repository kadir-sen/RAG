"""Tests for file routing logic."""
import pytest
from src.file_router import EXTENSION_MAP, ProcessingResult


class TestExtensionMap:
    def test_pdf_is_document(self):
        assert EXTENSION_MAP[".pdf"] == "document"

    def test_docx_is_document(self):
        assert EXTENSION_MAP[".docx"] == "document"

    def test_doc_is_document(self):
        assert EXTENSION_MAP[".doc"] == "document"

    def test_txt_is_document(self):
        assert EXTENSION_MAP[".txt"] == "document"

    def test_eml_is_email(self):
        assert EXTENSION_MAP[".eml"] == "email"

    def test_msg_is_email(self):
        assert EXTENSION_MAP[".msg"] == "email"

    def test_xlsx_is_data(self):
        assert EXTENSION_MAP[".xlsx"] == "data"

    def test_xls_is_data(self):
        assert EXTENSION_MAP[".xls"] == "data"

    def test_csv_is_data(self):
        assert EXTENSION_MAP[".csv"] == "data"

    def test_all_extensions_covered(self):
        assert len(EXTENSION_MAP) == 9


class TestProcessingResult:
    def test_default_values(self):
        result = ProcessingResult(success=True, file_path="/test.pdf", file_type="document")
        assert result.success is True
        assert result.ocr_pages == 0
        assert result.tables_extracted == 0
        assert result.total_rows == 0
        assert result.notice_extracted is False
        assert result.notice_summary is None
        assert result.attachments_processed == 0
        assert result.attachment_results == []
        assert result.converter_used is None
        assert result.converter_generated is False
        assert result.target_schema is None
        assert result.error is None

    def test_data_result_with_converter(self):
        result = ProcessingResult(
            success=True,
            file_path="/test.xlsx",
            file_type="data",
            tables_extracted=1,
            total_rows=100,
            converter_used="conv_abc123",
            converter_generated=True,
            target_schema="dpr",
        )
        assert result.converter_used == "conv_abc123"
        assert result.converter_generated is True
        assert result.target_schema == "dpr"

    def test_email_result_with_attachments(self):
        result = ProcessingResult(
            success=True,
            file_path="/test.eml",
            file_type="email",
            attachments_processed=2,
            attachment_results=[
                {"filename": "report.pdf", "success": True},
                {"filename": "data.xlsx", "success": True},
            ],
        )
        assert result.attachments_processed == 2
        assert len(result.attachment_results) == 2
