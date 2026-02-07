"""
Unified Ingestion Pipeline.
Orchestrates table extraction, notice extraction, and jargon loading from files.
"""
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field

from .logger import logger, log_separator
from .catalog import get_catalog, TableMetadata
from .excel_table_extractor import extract_excel_tables
from .pdf_table_extractor import extract_pdf_tables
from .ocr_detector import analyze_pdf
from .jargon_manager import get_jargon_manager


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

    # Notice extraction (Phase 2)
    notice_extracted: bool = False
    notice_path: Optional[str] = None
    notice_summary: Optional[Dict[str, Any]] = None


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
        # Initialize jargon manager (loads built-in + auto-discovers dictionary files)
        self.jargon = get_jargon_manager()

    def load_jargon_file(self, file_path: str) -> int:
        """
        Load a jargon dictionary file.

        Args:
            file_path: Path to jargon Excel file

        Returns:
            Number of terms loaded
        """
        return self.jargon.load_from_excel(file_path)

    def ingest_file(self, file_path: str) -> IngestionResult:
        """
        Ingest a file and extract tables.
        Auto-detects jargon dictionary files and loads them.

        Args:
            file_path: Path to file

        Returns:
            IngestionResult with extraction summary
        """
        path = Path(file_path)
        ext = path.suffix.lower()

        # Auto-detect and load jargon dictionary files
        name_lower = path.name.lower()
        if ext in ['.xlsx', '.xls'] and any(kw in name_lower for kw in ['jargon', 'abbreviation', 'kisaltma', 'glossary']):
            count = self.load_jargon_file(file_path)
            logger.info(f"[Ingestion] Loaded {count} jargon terms from: {path.name}")

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


def extract_document_notice(
    doc_id: str,
    file_path: str,
    doc_text_by_page: Dict[int, str],
    project_id: Optional[str] = None,
    use_llm: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Extract notice metadata from a document and update catalog.

    Args:
        doc_id: Unique document identifier
        file_path: Path to source file
        doc_text_by_page: Dict mapping page numbers to text content
        project_id: Optional project identifier
        use_llm: Whether to use LLM refinement

    Returns:
        Notice summary dict or None if extraction failed
    """
    try:
        from .notice_extractor import extract_and_save_notice
        from .light_graph import add_document_to_graph

        logger.info(f"[Notice] Extracting notice from: {Path(file_path).name}")

        # Extract and save notice
        notice, notice_path = extract_and_save_notice(
            doc_id=doc_id,
            file_path=file_path,
            doc_text_by_page=doc_text_by_page,
            project_id=project_id,
            use_llm=use_llm,
        )

        # Build notice summary
        notice_summary = {
            "date": notice.date,
            "sender": notice.sender,
            "recipient": notice.recipient,
            "subject": notice.subject[:100] if notice.subject else None,
            "doc_type": notice.doc_type,
            "ref_numbers": notice.ref_numbers[:3],
            "actions": notice.actions[:3],
        }

        # Update catalog with notice info
        catalog = get_catalog()
        catalog.update_notice(file_path, notice_path, notice_summary)

        # Add to document graph
        add_document_to_graph(notice)

        logger.info(f"[Notice] Extraction complete: date={notice.date}, sender={notice.sender[:30] if notice.sender else None}")

        return notice_summary

    except Exception as e:
        logger.error(f"[Notice] Extraction error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None
