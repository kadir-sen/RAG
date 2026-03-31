"""
PDF Table Extractor using pdfplumber and optional camelot.
Extracts tabular data from PDF pages with OCR detection integration.
"""
import re
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

import pandas as pd

from .logger import logger
from .catalog import get_catalog, TableMetadata
from .ocr import OCRDetector, OCRDecision

# Check for pdfplumber
try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    logger.warning("[PDFExtractor] pdfplumber not installed - table extraction limited")

# Check for camelot (optional, better for bordered tables)
try:
    import camelot
    CAMELOT_AVAILABLE = True
except ImportError:
    CAMELOT_AVAILABLE = False


@dataclass
class ExtractedPDFTable:
    """Represents a table extracted from a PDF page."""
    df: pd.DataFrame
    page_number: int
    table_index: int  # Multiple tables per page
    bbox: Optional[tuple] = None  # (x0, y0, x1, y1)
    extraction_method: str = "pdfplumber"


class PDFTableExtractor:
    """
    Extracts tables from PDF files using pdfplumber.
    Integrates with OCR detector to decide extraction strategy.
    """

    def __init__(self):
        """Initialize PDF table extractor."""
        self.catalog = get_catalog()
        self.ocr_detector = OCRDetector()

        if not PDFPLUMBER_AVAILABLE:
            logger.warning("[PDFExtractor] pdfplumber not available - install with: pip install pdfplumber")

    def extract_tables(
        self,
        file_path: str,
        pages: Optional[List[int]] = None,
        use_ocr_fallback: bool = True,
    ) -> List[ExtractedPDFTable]:
        """
        Extract all tables from a PDF file.

        Args:
            file_path: Path to PDF file
            pages: Specific pages to extract (1-indexed), None = all
            use_ocr_fallback: Whether to use OCR for scanned pages

        Returns:
            List of extracted tables
        """
        if not PDFPLUMBER_AVAILABLE:
            logger.error("[PDFExtractor] pdfplumber required for table extraction")
            return []

        path = Path(file_path)
        logger.info(f"[PDFExtractor] Processing: {path.name}")

        tables = []

        try:
            # Analyze document for OCR needs
            analysis = self.ocr_detector.analyze_document(file_path)
            logger.info(f"[PDFExtractor] OCR decision: {analysis.decision.value}")

            with pdfplumber.open(file_path) as pdf:
                total_pages = len(pdf.pages)

                # Determine which pages to process
                if pages:
                    page_nums = [p for p in pages if 1 <= p <= total_pages]
                else:
                    page_nums = list(range(1, total_pages + 1))

                for page_num in page_nums:
                    page = pdf.pages[page_num - 1]  # 0-indexed

                    # Check if page needs OCR
                    page_analysis = next(
                        (pa for pa in analysis.page_analyses if pa.page_number == page_num),
                        None
                    )
                    needs_ocr = page_analysis.needs_ocr if page_analysis else False

                    if needs_ocr and use_ocr_fallback:
                        logger.info(f"[PDFExtractor] Page {page_num}: Needs OCR, skipping table extraction")
                        # Table extraction from scanned pages requires OCR'd PDF
                        # This would integrate with OCRMyPDF if available
                        continue

                    # Extract tables from page
                    page_tables = self._extract_tables_from_page(page, page_num)
                    tables.extend(page_tables)

                    if page_tables:
                        logger.info(f"[PDFExtractor] Page {page_num}: Found {len(page_tables)} tables")

            logger.info(f"[PDFExtractor] Total tables extracted: {len(tables)}")

        except Exception as e:
            logger.error(f"[PDFExtractor] Error processing PDF: {e}")
            import traceback
            logger.error(traceback.format_exc())

        return tables

    def _extract_tables_from_page(
        self,
        page: "pdfplumber.Page",
        page_number: int
    ) -> List[ExtractedPDFTable]:
        """Extract tables from a single PDF page."""
        tables = []

        try:
            # Use pdfplumber's table extraction
            found_tables = page.extract_tables({
                "vertical_strategy": "lines_strict",
                "horizontal_strategy": "lines_strict",
                "snap_tolerance": 3,
                "join_tolerance": 3,
                "edge_min_length": 3,
            })

            # If strict mode finds nothing, try relaxed mode
            if not found_tables:
                found_tables = page.extract_tables({
                    "vertical_strategy": "text",
                    "horizontal_strategy": "text",
                    "snap_tolerance": 5,
                    "join_tolerance": 5,
                })

            for idx, table_data in enumerate(found_tables):
                if not table_data or len(table_data) < 2:
                    continue

                # Convert to DataFrame
                df = self._table_to_dataframe(table_data)

                if df.empty or len(df) < 2 or len(df.columns) < 2:
                    continue

                tables.append(ExtractedPDFTable(
                    df=df,
                    page_number=page_number,
                    table_index=idx,
                    extraction_method="pdfplumber",
                ))

        except Exception as e:
            logger.warning(f"[PDFExtractor] Error extracting tables from page {page_number}: {e}")

        # Try camelot as fallback for bordered tables
        if not tables and CAMELOT_AVAILABLE:
            camelot_tables = self._try_camelot(page, page_number)
            tables.extend(camelot_tables)

        return tables

    def _table_to_dataframe(self, table_data: List[List]) -> pd.DataFrame:
        """Convert raw table data to cleaned DataFrame."""
        if not table_data:
            return pd.DataFrame()

        # Find header row (first non-empty row)
        header_idx = 0
        for i, row in enumerate(table_data):
            if row and any(cell for cell in row if cell):
                header_idx = i
                break

        headers = table_data[header_idx]
        body = table_data[header_idx + 1:]

        if not headers or not body:
            return pd.DataFrame()

        # Clean headers
        clean_headers = []
        for i, h in enumerate(headers):
            if h is None or str(h).strip() == '':
                clean_headers.append(f"col_{i}")
            else:
                clean = str(h).strip()
                clean = re.sub(r'[^a-zA-Z0-9_]', '_', clean)
                clean = re.sub(r'_+', '_', clean).strip('_').lower()
                if not clean:
                    clean = f"col_{i}"
                clean_headers.append(clean)

        # Handle duplicate headers
        seen = {}
        final_headers = []
        for h in clean_headers:
            if h in seen:
                seen[h] += 1
                final_headers.append(f"{h}_{seen[h]}")
            else:
                seen[h] = 0
                final_headers.append(h)

        # Create DataFrame
        df = pd.DataFrame(body, columns=final_headers)

        # Clean values
        for col in df.columns:
            df[col] = df[col].apply(lambda x: str(x).strip() if x else None)
            df[col] = df[col].replace(['', 'None', 'nan'], None)

        # Drop empty rows
        df = df.dropna(how='all')

        return df

    def _try_camelot(
        self,
        page: "pdfplumber.Page",
        page_number: int
    ) -> List[ExtractedPDFTable]:
        """Try camelot for bordered table extraction."""
        tables = []

        try:
            # Camelot works on file path, need the PDF path
            # This is a simplified implementation
            # Full implementation would need the file path passed through

            logger.debug(f"[PDFExtractor] Camelot fallback for page {page_number}")

        except Exception as e:
            logger.debug(f"[PDFExtractor] Camelot failed: {e}")

        return tables

    def save_to_parquet(
        self,
        table: ExtractedPDFTable,
        source_file: str
    ) -> Optional[TableMetadata]:
        """
        Save extracted table to Parquet and register in catalog.

        Args:
            table: Extracted table
            source_file: Original PDF path

        Returns:
            TableMetadata if successful
        """
        try:
            # Generate table ID
            table_id = self.catalog.generate_table_id(
                source_file,
                page_number=table.page_number,
                table_index=table.table_index,
            )

            # Generate parquet path
            parquet_path = self.catalog.generate_parquet_path(table_id)

            # Save to parquet
            table.df.to_parquet(parquet_path, index=False)

            logger.info(f"[PDFExtractor] Saved parquet: {parquet_path.name}")

            # Create metadata
            meta = TableMetadata(
                table_id=table_id,
                source_file=source_file,
                source_type="pdf",
                table_name=table_id,
                parquet_path=str(parquet_path),
                page_number=table.page_number,
                table_index=table.table_index,
                row_count=len(table.df),
                column_count=len(table.df.columns),
                columns=list(table.df.columns),
                extraction_method=table.extraction_method,
                file_hash=self.catalog.compute_file_hash(source_file),
            )

            return meta

        except Exception as e:
            logger.error(f"[PDFExtractor] Error saving parquet: {e}")
            return None


def extract_pdf_tables(
    file_path: str,
    save_parquet: bool = True,
    pages: Optional[List[int]] = None,
) -> List[TableMetadata]:
    """
    Extract tables from PDF file and optionally save to parquet.

    Args:
        file_path: Path to PDF file
        save_parquet: If True, save tables to parquet files
        pages: Specific pages to extract (1-indexed)

    Returns:
        List of TableMetadata for extracted tables
    """
    extractor = PDFTableExtractor()
    tables = extractor.extract_tables(file_path, pages=pages)

    if not save_parquet or not tables:
        return []

    catalog = get_catalog()

    # Analyze OCR decision for entry
    detector = OCRDetector()
    analysis = detector.analyze_document(file_path)

    entry = catalog.add_entry(
        file_path,
        "pdf",
        ocr_decision=analysis.decision.value
    )

    metadata_list = []
    for table in tables:
        meta = extractor.save_to_parquet(table, file_path)
        if meta:
            catalog.add_table(entry, meta)
            metadata_list.append(meta)

    return metadata_list
