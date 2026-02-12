"""
Unit tests for Table Extraction Pipeline.

Run with: pytest tests/test_table_extraction.py -v
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import tempfile
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCatalog:
    """Tests for TableCatalog."""

    def test_catalog_initialization(self, tmp_path):
        """Test catalog initializes correctly."""
        from src.catalog import TableCatalog

        catalog = TableCatalog(
            catalog_path=tmp_path / "catalog.json",
            parquet_dir=tmp_path / "parquet",
        )

        assert catalog.catalog_path == tmp_path / "catalog.json"
        assert catalog.parquet_dir == tmp_path / "parquet"
        assert len(catalog.entries) == 0

    def test_generate_table_id(self, tmp_path):
        """Test table ID generation."""
        from src.catalog import TableCatalog

        catalog = TableCatalog(
            catalog_path=tmp_path / "catalog.json",
            parquet_dir=tmp_path / "parquet",
        )

        # Basic ID
        table_id = catalog.generate_table_id("test_file.xlsx")
        assert table_id.startswith("test_file_")
        assert len(table_id) > 10

        # With sheet name
        table_id_sheet = catalog.generate_table_id("test_file.xlsx", sheet_name="Sheet1")
        assert "sheet1" in table_id_sheet.lower()

        # With page number
        table_id_page = catalog.generate_table_id("document.pdf", page_number=5)
        assert "p5" in table_id_page

    def test_add_and_get_entry(self, tmp_path):
        """Test adding and retrieving catalog entries."""
        from src.catalog import TableCatalog

        catalog = TableCatalog(
            catalog_path=tmp_path / "catalog.json",
            parquet_dir=tmp_path / "parquet",
        )

        # Create a dummy file
        test_file = tmp_path / "test.xlsx"
        test_file.write_text("dummy content")

        # Add entry
        entry = catalog.add_entry(str(test_file), "excel")

        assert entry.source_file == str(test_file)
        assert entry.source_type == "excel"
        assert len(catalog.entries) == 1

        # Get entry
        retrieved = catalog.get_entry(str(test_file))
        assert retrieved is not None
        assert retrieved.source_file == str(test_file)

    def test_catalog_persistence(self, tmp_path):
        """Test catalog saves and loads correctly."""
        from src.catalog import TableCatalog, TableMetadata

        catalog_path = tmp_path / "catalog.json"
        parquet_dir = tmp_path / "parquet"

        # Create catalog and add entry
        catalog1 = TableCatalog(catalog_path=catalog_path, parquet_dir=parquet_dir)

        test_file = tmp_path / "test.xlsx"
        test_file.write_text("dummy")

        entry = catalog1.add_entry(str(test_file), "excel")

        # Add a table
        meta = TableMetadata(
            table_id="test_table",
            source_file=str(test_file),
            source_type="excel",
            table_name="test_table",
            parquet_path=str(parquet_dir / "test.parquet"),
            row_count=100,
            column_count=5,
        )
        catalog1.add_table(entry, meta)

        # Load new catalog instance
        catalog2 = TableCatalog(catalog_path=catalog_path, parquet_dir=parquet_dir)

        assert len(catalog2.entries) == 1
        tables = catalog2.get_all_tables()
        assert len(tables) == 1
        assert tables[0].table_id == "test_table"


class TestExcelTableExtractor:
    """Tests for ExcelTableExtractor."""

    def test_clean_dataframe(self):
        """Test DataFrame cleaning."""
        from src.excel_table_extractor import ExcelTableExtractor

        extractor = ExcelTableExtractor()

        # Create messy DataFrame
        df = pd.DataFrame({
            "Name ": ["John", "Jane", None],
            "Age!": [25, 30, 35],
            "": ["A", "B", "C"],
        })

        cleaned = extractor._clean_dataframe(df)

        # Check columns are cleaned
        assert "name" in cleaned.columns
        assert "age" in cleaned.columns
        assert "col_2" in cleaned.columns  # Empty column renamed

        # Check empty row is dropped
        assert len(cleaned) == 3

    def test_parse_cell_ref(self):
        """Test cell reference parsing."""
        from src.excel_table_extractor import ExcelTableExtractor

        col, row = ExcelTableExtractor._parse_cell_ref("A1")
        assert col == 1
        assert row == 1

        col, row = ExcelTableExtractor._parse_cell_ref("Z10")
        assert col == 26
        assert row == 10

        col, row = ExcelTableExtractor._parse_cell_ref("AA1")
        assert col == 27
        assert row == 1


class TestOCRDetector:
    """Tests for OCR Detector."""

    def test_ocr_decision_enum(self):
        """Test OCR decision enum values."""
        from src.ocr_detector import OCRDecision

        assert OCRDecision.NATIVE.value == "native"
        assert OCRDecision.OCR.value == "ocr"
        assert OCRDecision.HYBRID.value == "hybrid"

    @patch('src.ocr_detector.fitz')
    def test_analyze_page_with_text(self, mock_fitz):
        """Test page analysis with sufficient text."""
        from src.ocr_detector import OCRDetector

        detector = OCRDetector(min_chars=30, min_alpha_ratio=0.2)

        # Mock page with good text
        mock_page = Mock()
        mock_page.get_text.return_value = "This is a normal page with plenty of text content for analysis."
        mock_page.get_images.return_value = []
        mock_page.rect.width = 100
        mock_page.rect.height = 100

        analysis = detector._analyze_page(mock_page, 1)

        assert analysis.needs_ocr is False
        assert analysis.char_count > 30
        assert analysis.alpha_ratio > 0.2

    @patch('src.ocr_detector.fitz')
    def test_analyze_page_empty(self, mock_fitz):
        """Test page analysis with no text."""
        from src.ocr_detector import OCRDetector

        detector = OCRDetector(min_chars=30)

        # Mock empty page
        mock_page = Mock()
        mock_page.get_text.return_value = ""
        mock_page.get_images.return_value = []
        mock_page.rect.width = 100
        mock_page.rect.height = 100

        analysis = detector._analyze_page(mock_page, 1)

        assert analysis.needs_ocr is True
        assert analysis.char_count == 0


class TestDataAnalyzerParquet:
    """Tests for Parquet view support in DataAnalyzer."""

    def test_register_parquet_view(self, tmp_path):
        """Test registering a parquet file as a view."""
        from src.data_analyzer_sql import DataAnalyzerSQL

        # Create a test parquet file
        df = pd.DataFrame({
            "name": ["Alice", "Bob", "Charlie"],
            "age": [25, 30, 35],
        })
        parquet_path = tmp_path / "test.parquet"
        df.to_parquet(parquet_path, index=False)

        # Initialize analyzer and register view
        with patch('src.data_analyzer_sql.GOOGLE_API_KEY', 'test_key'):
            analyzer = DataAnalyzerSQL()
            success = analyzer.register_parquet_view(str(parquet_path))

            assert success is True
            assert "test" in analyzer.tables

            # Query the view
            result = analyzer.conn.execute("SELECT * FROM test").fetchdf()
            assert len(result) == 3


class TestTableIngestion:
    """Tests for TableIngestionPipeline."""

    def test_supported_extensions(self):
        """Test supported file extensions."""
        from src.table_ingestion import TableIngestionPipeline

        pipeline = TableIngestionPipeline()

        assert '.xlsx' in pipeline.SUPPORTED_EXTENSIONS
        assert '.xls' in pipeline.SUPPORTED_EXTENSIONS
        assert '.csv' in pipeline.SUPPORTED_EXTENSIONS
        assert '.pdf' in pipeline.SUPPORTED_EXTENSIONS
        assert '.txt' not in pipeline.SUPPORTED_EXTENSIONS

    def test_ingest_unsupported_file(self, tmp_path):
        """Test ingestion of unsupported file type."""
        from src.table_ingestion import TableIngestionPipeline

        pipeline = TableIngestionPipeline()

        # Create a text file
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")

        result = pipeline.ingest_file(str(test_file))

        assert result.success is False
        assert "Unsupported" in result.error


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
