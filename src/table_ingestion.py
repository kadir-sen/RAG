"""
Unified Table Ingestion Pipeline.
Orchestrates table extraction from Excel and PDF files.
"""
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from .logger import logger, log_separator
from .catalog import get_catalog, TableMetadata
from .excel_table_extractor import extract_excel_tables
from .pdf_table_extractor import extract_pdf_tables
from .ocr_detector import analyze_pdf


@dataclass
class IngestionResult:
    """Result of ingesting a file."""
    file_path: str
    file_type: str
    success: bool
    tables_extracted: int
    total_rows: int
    ocr_decision: Optional[str] = None
    error: Optional[str] = None


class TableIngestionPipeline:
    """
    Unified pipeline for extracting and storing tables from various file types.
    Automatically detects table regions and stores as Parquet files.
    """

    SUPPORTED_EXTENSIONS = {
        '.xlsx': 'excel',
        '.xls': 'excel',
        '.csv': 'excel',  # Treat CSV like Excel
        '.pdf': 'pdf',
    }

    def __init__(self):
        """Initialize ingestion pipeline."""
        self.catalog = get_catalog()

    def ingest_file(self, file_path: str) -> IngestionResult:
        """
        Ingest a file and extract tables.

        Args:
            file_path: Path to file

        Returns:
            IngestionResult with extraction summary
        """
        path = Path(file_path)
        ext = path.suffix.lower()

        if ext not in self.SUPPORTED_EXTENSIONS:
            return IngestionResult(
                file_path=file_path,
                file_type="unknown",
                success=False,
                tables_extracted=0,
                total_rows=0,
                error=f"Unsupported file type: {ext}",
            )

        file_type = self.SUPPORTED_EXTENSIONS[ext]

        log_separator(f"Ingesting: {path.name}")
        logger.info(f"[Ingestion] Type: {file_type}")

        try:
            if file_type == 'excel':
                return self._ingest_excel(file_path)
            elif file_type == 'pdf':
                return self._ingest_pdf(file_path)
            else:
                return IngestionResult(
                    file_path=file_path,
                    file_type=file_type,
                    success=False,
                    tables_extracted=0,
                    total_rows=0,
                    error="Unknown file type",
                )

        except Exception as e:
            logger.error(f"[Ingestion] Error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return IngestionResult(
                file_path=file_path,
                file_type=file_type,
                success=False,
                tables_extracted=0,
                total_rows=0,
                error=str(e),
            )

    def _ingest_excel(self, file_path: str) -> IngestionResult:
        """Ingest Excel/CSV file."""
        metadata_list = extract_excel_tables(file_path, save_parquet=True)

        total_rows = sum(m.row_count for m in metadata_list)

        logger.info(f"[Ingestion] Excel complete: {len(metadata_list)} tables, {total_rows} rows")

        return IngestionResult(
            file_path=file_path,
            file_type="excel",
            success=len(metadata_list) > 0,
            tables_extracted=len(metadata_list),
            total_rows=total_rows,
        )

    def _ingest_pdf(self, file_path: str) -> IngestionResult:
        """Ingest PDF file with table extraction."""
        # First analyze for OCR needs
        analysis = analyze_pdf(file_path)
        ocr_decision = analysis.decision.value

        logger.info(f"[Ingestion] OCR decision: {ocr_decision}")

        # Extract tables (will skip OCR pages)
        metadata_list = extract_pdf_tables(file_path, save_parquet=True)

        total_rows = sum(m.row_count for m in metadata_list)

        logger.info(f"[Ingestion] PDF complete: {len(metadata_list)} tables, {total_rows} rows")

        return IngestionResult(
            file_path=file_path,
            file_type="pdf",
            success=True,  # Even 0 tables is OK for PDFs (might be text-only)
            tables_extracted=len(metadata_list),
            total_rows=total_rows,
            ocr_decision=ocr_decision,
        )

    def ingest_folder(self, folder_path: str) -> Dict[str, Any]:
        """
        Ingest all supported files from a folder.

        Args:
            folder_path: Path to folder

        Returns:
            Summary of ingestion results
        """
        folder = Path(folder_path)

        if not folder.exists():
            return {
                "success": False,
                "error": f"Folder not found: {folder_path}",
                "files_processed": 0,
                "tables_extracted": 0,
            }

        log_separator(f"Ingesting folder: {folder.name}")

        results = []
        for ext in self.SUPPORTED_EXTENSIONS.keys():
            for file_path in folder.rglob(f"*{ext}"):
                # Skip temp files
                if file_path.name.startswith('~$'):
                    continue
                result = self.ingest_file(str(file_path))
                results.append(result)

        # Summarize
        successful = [r for r in results if r.success]
        total_tables = sum(r.tables_extracted for r in results)
        total_rows = sum(r.total_rows for r in results)

        summary = {
            "success": True,
            "files_processed": len(results),
            "files_successful": len(successful),
            "tables_extracted": total_tables,
            "total_rows": total_rows,
            "by_type": self._summarize_by_type(results),
        }

        logger.info(f"[Ingestion] Folder complete: {len(results)} files, {total_tables} tables")

        return summary

    def _summarize_by_type(self, results: List[IngestionResult]) -> Dict[str, Dict]:
        """Summarize results by file type."""
        by_type = {}

        for r in results:
            if r.file_type not in by_type:
                by_type[r.file_type] = {
                    "files": 0,
                    "tables": 0,
                    "rows": 0,
                }

            by_type[r.file_type]["files"] += 1
            by_type[r.file_type]["tables"] += r.tables_extracted
            by_type[r.file_type]["rows"] += r.total_rows

        return by_type

    def get_ingestion_stats(self) -> Dict[str, Any]:
        """Get overall ingestion statistics from catalog."""
        return self.catalog.get_stats()


# Convenience functions
def ingest_file(file_path: str) -> IngestionResult:
    """
    Ingest a single file.

    Args:
        file_path: Path to file

    Returns:
        IngestionResult
    """
    pipeline = TableIngestionPipeline()
    return pipeline.ingest_file(file_path)


def ingest_folder(folder_path: str) -> Dict[str, Any]:
    """
    Ingest all files in a folder.

    Args:
        folder_path: Path to folder

    Returns:
        Summary dictionary
    """
    pipeline = TableIngestionPipeline()
    return pipeline.ingest_folder(folder_path)
