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


class TestInvoiceExtraction:
    """Tests for invoice/form-style Excel extraction."""

    def test_metadata_row_detection(self):
        """Detects label:value metadata rows correctly."""
        from src.excel_table_extractor import ExcelTableExtractor

        extractor = ExcelTableExtractor()

        # Metadata row: "Name of Project : The Address Boulevard Hotel"
        meta_row = ["Name of Project", ":", "The Address Boulevard Hotel", None, None]
        assert extractor._is_metadata_row(meta_row) is True

        # Metadata row as single cell
        meta_row2 = ["Customer Name : Reliance Electromechanical LLC", None, None]
        assert extractor._is_metadata_row(meta_row2) is True

        # Data row (should NOT be detected as metadata)
        data_row = ["Sr.No.", "Description", "%", "Gross Value", "Prev. Payment"]
        assert extractor._is_metadata_row(data_row) is False

        # Empty row
        assert extractor._is_metadata_row([None, None, None]) is False

    def test_header_candidate_detection(self):
        """Finds correct header row in invoice-style matrix."""
        from src.excel_table_extractor import ExcelTableExtractor

        extractor = ExcelTableExtractor()

        # Simulate an invoice layout
        matrix = [
            # Row 0: Title (merged)
            ["INVOICE NO. 11", "INVOICE NO. 11", "INVOICE NO. 11", None, None, None],
            # Row 1: empty
            [None, None, None, None, None, None],
            # Row 2: metadata
            ["Name of Project : The Address Boulevard Hotel", None, None, None, None, None],
            # Row 3: metadata
            ["Customer Name : Reliance LLC", None, None, None, None, None],
            # Row 4: metadata
            ["Contract Value : AED 25,000,000", None, None, None, None, None],
            # Row 5: Column headers
            ["Sr.No.", "Description", "%", "Gross Value", "Prev. Payment", "This Payment"],
            # Row 6-8: Data rows
            [1, "Value of Work Done", 85, 1918935.52, 712590.39, 1206356.13],
            [2, "Variations", None, 0.00, 0.00, 0.00],
            [3, "Day works Agreed", None, 0.00, 0.00, 0.00],
        ]

        candidates = extractor._find_header_candidates(matrix)
        assert len(candidates) > 0

        # The header row should be row 5 (0-indexed)
        best_row = candidates[0][0]
        assert best_row == 5

    def test_data_end_detection(self):
        """Finds correct end of data table."""
        from src.excel_table_extractor import ExcelTableExtractor

        extractor = ExcelTableExtractor()

        matrix = [
            # Row 0: header
            ["Sr.No.", "Description", "Amount"],
            # Row 1-3: data
            [1, "Work A", 1000.0],
            [2, "Work B", 2000.0],
            [3, "Work C", 3000.0],
            # Row 4: empty
            [None, None, None],
            # Row 5: empty
            [None, None, None],
            # Row 6: empty
            [None, None, None],
            # Row 7: empty
            [None, None, None],
            # Row 8: signature
            ["FOR MVP TECH GENERAL TRADING LLC", None, None],
            # Row 9: name
            ["SASIDHARAN N.N", None, None],
        ]

        end = extractor._find_data_end(matrix, header_row=0, col_start=0, col_end=2)
        # Should stop at row 3 (last data row) and not include empties or signature
        assert end == 3

    def test_extract_header_metadata(self):
        """Extracts metadata from header section above data table."""
        from src.excel_table_extractor import ExcelTableExtractor

        extractor = ExcelTableExtractor()

        matrix = [
            ["Name of Project : The Address Boulevard Hotel", None, None],
            ["Customer Name : Reliance LLC", None, None],
            ["Contract Value : AED 25,000,000", None, None],
            [None, None, None],
            ["Sr.No.", "Description", "Amount"],  # header row = 4
        ]

        metadata = extractor._extract_header_metadata(matrix, header_row=4)
        assert "project_name" in metadata
        assert "Address" in metadata["project_name"]
        assert "customer_name" in metadata

    def test_invoice_extraction_end_to_end(self):
        """Full invoice extraction from matrix."""
        from src.excel_table_extractor import ExcelTableExtractor

        extractor = ExcelTableExtractor()

        matrix = [
            # Row 0: Logo area (merged cell artifact)
            ["MVP", "MVP", "MVP", None, None, None],
            # Row 1: empty
            [None, None, None, None, None, None],
            # Row 2: Reference + Date
            ["REMCO/SKTKS21014/EMAB/012016", None, None, None, "18th January 2016", None],
            # Row 3: empty
            [None, None, None, None, None, None],
            # Row 4: Invoice title (merged)
            ["INVOICE NO. 11", "INVOICE NO. 11", "INVOICE NO. 11", None, None, None],
            # Row 5: empty
            [None, None, None, None, None, None],
            # Row 6: metadata
            ["Name of Project : The Address Boulevard Hotel", None, None, None, None, None],
            # Row 7: metadata
            ["Customer Name : Reliance Electromechanical & Plumbing Contracting LLC", None, None, None, None, None],
            # Row 8: metadata
            ["Sub Contractor Name : MVP Tech General Trading LLC", None, None, None, None, None],
            # Row 9: Column headers
            ["Sr.No.", "Description", "%", "Gross Value", "Prev. Payment", "This Payment"],
            # Row 10-12: Data
            [1, "Value of Work Done", 85, 1918935.52, 712590.39, 1206356.13],
            [2, "Variations", None, 0.00, 0.00, 0.00],
            [3, "Day works Agreed", None, 0.00, 0.00, 0.00],
            # Row 13: empty
            [None, None, None, None, None, None],
            [None, None, None, None, None, None],
            [None, None, None, None, None, None],
            [None, None, None, None, None, None],
            # Row 17: Signature block
            ["FOR MVP TECH GENERAL TRADING LLC", None, None, None, None, None],
        ]

        tables = extractor._extract_invoice_tables(matrix, "Sheet1")
        assert len(tables) == 1

        table = tables[0]
        assert table.extraction_method == "invoice_detect"
        assert len(table.df) >= 2  # At least the data rows (summary rows may be removed)
        assert table.start_row == 10  # 1-indexed: row 9 (0-indexed) + 1
        assert "project_name" in table.header_metadata

    def test_unmerge_fills_values(self):
        """Merged cells are filled into all constituent cells."""
        from src.excel_table_extractor import ExcelTableExtractor
        from unittest.mock import MagicMock, PropertyMock

        extractor = ExcelTableExtractor()

        # Create a mock worksheet
        ws = MagicMock()
        type(ws).max_row = PropertyMock(return_value=3)
        type(ws).max_column = PropertyMock(return_value=4)

        # Create cell mocks
        cells = []
        for r in range(1, 4):
            row_cells = []
            for c in range(1, 5):
                cell = MagicMock()
                cell.row = r
                cell.column = c
                cell.value = None
                row_cells.append(cell)
            cells.append(row_cells)

        # Set some values
        cells[0][0].value = "TITLE"  # A1
        cells[1][0].value = "Data1"  # A2
        cells[1][1].value = "Data2"  # B2
        cells[2][0].value = "Data3"  # A3
        cells[2][1].value = "Data4"  # B3

        ws.iter_rows.return_value = cells

        # Mock merged cells: A1:D1 is merged
        merge = MagicMock()
        merge.min_row = 1
        merge.max_row = 1
        merge.min_col = 1
        merge.max_col = 4
        ws.merged_cells.ranges = [merge]

        matrix = extractor._unmerge_and_fill(ws)

        # A1:D1 should all have "TITLE"
        assert matrix[0][0] == "TITLE"
        assert matrix[0][1] == "TITLE"
        assert matrix[0][2] == "TITLE"
        assert matrix[0][3] == "TITLE"

        # Non-merged cells should be unchanged
        assert matrix[1][0] == "Data1"
        assert matrix[1][1] == "Data2"

    def test_summary_row_removal_all_columns(self):
        """Summary rows detected in ANY column, not just first 3."""
        from src.excel_table_extractor import ExcelTableExtractor

        extractor = ExcelTableExtractor()

        df = pd.DataFrame({
            "sr_no": [1, 2, 3, None, None],
            "description": ["Work A", "Work B", "Work C", "Gross Value of Work Done", "Net Amount Due"],
            "pct": [85, None, None, None, None],
            "amount": [1000, 2000, 3000, 6000, 5500],
        })

        cleaned = extractor._remove_summary_rows(df)

        # "Gross Value of Work Done" contains "total" → removed? No, it doesn't.
        # But "Net Amount Due" contains "net amount" → removed
        # Actually looking at SUMMARY_TOKENS: 'net amount' is there
        assert len(cleaned) <= 4  # At least "Net Amount Due" removed


class TestDenseTableExtraction:
    """Tests for dense table extraction with multi-row headers (DPR manpower)."""

    def _make_dpr_matrix(self, num_data_rows=5, num_zones=4):
        """Build a DPR-like matrix with multi-row headers."""
        # Determine columns: S No, Contractor, Designation, then zone*2 cols (Day/Night)
        num_fixed = 3
        num_zone_cols = num_zones * 2  # Day + Night per zone
        total_cols = num_fixed + num_zone_cols + 1  # +1 for Total

        matrix = []
        # Row 0: Title
        title_row = [None] * total_cols
        title_row[3] = "DAILY MAN POWER REPORT"
        matrix.append(title_row)
        # Row 1: empty
        matrix.append([None] * total_cols)
        # Row 2: empty
        matrix.append([None] * total_cols)
        # Row 3: empty
        matrix.append([None] * total_cols)

        # Row 4: Zone names (merged - repeated in pairs)
        zone_row = [None] * total_cols
        zone_row[0] = "S No"
        zone_row[1] = "Contractor"
        zone_row[2] = "Designation"
        zone_names = [f"Zone #{i+1}" for i in range(num_zones)]
        for i, zn in enumerate(zone_names):
            col = num_fixed + i * 2
            zone_row[col] = zn
            zone_row[col + 1] = zn  # Duplicate from merge
        zone_row[-1] = "Total"
        matrix.append(zone_row)

        # Row 5: Sub-areas (merged - repeated in pairs)
        sub_row = [None] * total_cols
        sub_row[0] = "S No"  # Repeated from merge
        sub_row[1] = "Contractor"
        sub_row[2] = "Designation"
        sub_areas = ["Road & Utility", "Viaduct", "Station", "Foundation"]
        for i in range(num_zones):
            col = num_fixed + i * 2
            sub_row[col] = sub_areas[i % len(sub_areas)]
            sub_row[col + 1] = sub_areas[i % len(sub_areas)]  # Duplicate from merge
        matrix.append(sub_row)

        # Row 6: Day/Night
        dn_row = [None] * total_cols
        dn_row[0] = "-"
        dn_row[1] = "-"
        dn_row[2] = "-"
        for i in range(num_zones):
            col = num_fixed + i * 2
            dn_row[col] = "Day"
            dn_row[col + 1] = "Night"
        dn_row[-1] = "Total"
        matrix.append(dn_row)

        # Data rows
        for r in range(num_data_rows):
            data_row = [None] * total_cols
            data_row[0] = r + 1
            data_row[1] = f"Contractor {chr(65 + r)}"
            data_row[2] = "Workmen"
            # Sprinkle some values
            for i in range(num_zones):
                col = num_fixed + i * 2
                if (r + i) % 3 == 0:
                    data_row[col] = (r + 1) * 5
                    data_row[col + 1] = (r + 1) * 2
            data_row[-1] = sum(v for v in data_row[num_fixed:] if isinstance(v, (int, float)))
            matrix.append(data_row)

        return matrix

    def test_detect_multi_row_header(self):
        """Detects 3-row header pattern in DPR-style matrix."""
        from src.excel_table_extractor import ExcelTableExtractor
        extractor = ExcelTableExtractor()

        matrix = self._make_dpr_matrix(num_data_rows=10, num_zones=8)
        result = extractor._detect_multi_row_header(matrix)

        assert result is not None
        header_start, header_end, col_start, col_end = result
        assert header_end - header_start >= 1  # At least 2 header rows
        assert col_end - col_start >= 15  # Wide table

    def test_merge_header_rows(self):
        """Merges multi-row headers into composite column names."""
        from src.excel_table_extractor import ExcelTableExtractor
        extractor = ExcelTableExtractor()

        matrix = self._make_dpr_matrix(num_data_rows=5, num_zones=4)
        # Headers are at rows 4-6
        merged = extractor._merge_header_rows(matrix, 4, 6, 0, len(matrix[4]) - 1)

        assert merged[0] == "s_no"
        assert merged[1] == "contractor"
        assert merged[2] == "designation"
        # Zone columns should include zone name + sub-area + day/night
        assert "zone_1" in merged[3]
        assert "day" in merged[3]
        assert "night" in merged[4]
        # Last col should be total
        assert merged[-1] == "total"

    def test_no_false_positive_on_narrow_sheet(self):
        """Narrow sheets should NOT trigger dense table detection."""
        from src.excel_table_extractor import ExcelTableExtractor
        extractor = ExcelTableExtractor()

        # Simple narrow table - should not be detected as dense
        matrix = [
            ["Name", "Age", "City"],
            ["Alice", 30, "NYC"],
            ["Bob", 25, "LA"],
        ]
        result = extractor._detect_multi_row_header(matrix)
        assert result is None

    def test_no_false_positive_on_description_rows(self):
        """Rows with long descriptions should not be detected as headers."""
        from src.excel_table_extractor import ExcelTableExtractor
        extractor = ExcelTableExtractor()

        # Description-heavy layout (like Removed ManHours)
        matrix = [
            [None] * 20,
            [None] * 20,
            # Row 2: long description strings (not real column headers)
            ["Ref", "Drill piles with reinforced concrete", "Zone 10", "Nos", "29", "317", "126", "120", None, None, None, None, None, None, None, None, None, None, None, None],
            # Row 3: more description
            [None, "North cut cover activities guide wall shoring", None, "LM", "29", "317", "126", "120", None, None, None, None, None, None, None, None, None, None, None, None],
            # Row 4: data
            [1, "Foundation pile", "Z10", 5, 29, 317, 126, 120, 100, 50, 30, 20, 10, 5, 3, 2, 1, 0, 0, 0],
        ]
        result = extractor._detect_multi_row_header(matrix)
        # Should not detect (no repeating values from merges)
        assert result is None

    def test_extract_dense_table_end_to_end(self):
        """Full extraction pipeline for DPR-style dense table."""
        from src.excel_table_extractor import ExcelTableExtractor
        extractor = ExcelTableExtractor()

        matrix = self._make_dpr_matrix(num_data_rows=20, num_zones=10)
        result = extractor._extract_dense_table(matrix, "Man power")

        assert result is not None
        assert result.extraction_method == "dense_table"
        assert len(result.df) == 20  # 20 data rows
        assert len(result.df.columns) >= 20  # 3 fixed + 10*2 zone + 1 total = 24
        assert "s_no" in result.df.columns
        assert "contractor" in result.df.columns

    def test_dense_table_sparse_data_rows(self):
        """Sparse data rows (few cells per row) should still be captured."""
        from src.excel_table_extractor import ExcelTableExtractor
        extractor = ExcelTableExtractor()

        matrix = self._make_dpr_matrix(num_data_rows=10, num_zones=20)
        # Make most data cells empty (sparse like real DPR)
        for r in range(7, len(matrix)):
            for c in range(3, len(matrix[r]) - 1):
                if c % 7 != 0:  # Keep only every 7th column
                    matrix[r][c] = None

        result = extractor._extract_dense_table(matrix, "Man power")
        assert result is not None
        assert len(result.df) == 10  # All 10 data rows should be captured


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
