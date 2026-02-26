"""
File Router - Route uploaded files to the correct processing pipeline.
Single upload zone dispatches by file extension:
  PDF/DOC/TXT  → RAG pipeline + notice extraction
  EML/MSG      → Email parser → RAG + notice + recursive attachments
  XLSX/XLS/CSV → Format converter (try first) → fallback to existing pipeline
"""
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

import pandas as pd

from .logger import logger


# Extension to file type mapping
EXTENSION_MAP = {
    ".pdf": "document",
    ".docx": "document",
    ".doc": "document",
    ".txt": "document",
    ".eml": "email",
    ".msg": "email",
    ".xlsx": "data",
    ".xls": "data",
    ".csv": "data",
}


@dataclass
class ProcessingResult:
    """Result of processing a file through the pipeline."""
    success: bool
    file_path: str
    file_type: str  # "document" | "email" | "data" | "unknown"
    ocr_pages: int = 0
    tables_extracted: int = 0
    total_rows: int = 0
    notice_extracted: bool = False
    notice_summary: Optional[Dict] = None
    attachments_processed: int = 0
    attachment_results: List[Any] = field(default_factory=list)
    converter_used: Optional[str] = None
    converter_generated: bool = False
    target_schema: Optional[str] = None
    error: Optional[str] = None


def route_file(file_path: str) -> ProcessingResult:
    """
    Route a file to the correct processing pipeline based on extension.

    Args:
        file_path: Path to the saved file on disk

    Returns:
        ProcessingResult with processing outcome
    """
    ext = Path(file_path).suffix.lower()
    file_type = EXTENSION_MAP.get(ext, "unknown")

    logger.info(f"[FileRouter] Routing {Path(file_path).name} -> {file_type}")

    if file_type == "document":
        return _process_document(file_path)
    elif file_type == "email":
        return _process_email(file_path)
    elif file_type == "data":
        return _process_data_file(file_path)
    else:
        return ProcessingResult(
            success=False,
            file_path=file_path,
            file_type="unknown",
            error=f"Unsupported file type: {ext}",
        )


def _process_document(file_path: str) -> ProcessingResult:
    """Process a document file (PDF, DOCX, TXT) through RAG pipeline."""
    from .document_rag import get_document_rag
    from .data_analyzer_sql import get_data_analyzer

    result = ProcessingResult(success=False, file_path=file_path, file_type="document")
    filename = Path(file_path).name

    try:
        rag = get_document_rag()
        new_docs = rag.add_document(file_path)

        if new_docs:
            rag.insert_documents(new_docs)
            result.success = True

            # OCR stats
            file_info = rag.file_registry.get(filename, {})
            result.ocr_pages = file_info.get("ocr_pages", 0)

            # Notice extraction
            try:
                from .table_ingestion import extract_document_notice
                from .document_rag import generate_doc_id

                doc_text_by_page = {}
                for doc in rag.documents:
                    if doc.metadata.get("file_name") == filename:
                        page_num = doc.metadata.get("page_number", 1)
                        doc_text_by_page[page_num] = doc.text

                if doc_text_by_page:
                    doc_id = generate_doc_id(file_path)
                    notice_summary = extract_document_notice(
                        doc_id=doc_id,
                        file_path=file_path,
                        doc_text_by_page=doc_text_by_page,
                        use_llm=False,
                    )
                    if notice_summary:
                        result.notice_extracted = True
                        result.notice_summary = notice_summary
            except Exception as e:
                logger.warning(f"[FileRouter] Notice extraction error: {e}")

            # Table extraction for PDFs
            if filename.lower().endswith(".pdf"):
                try:
                    from .table_ingestion import ingest_file
                    ingestion_result = ingest_file(file_path)
                    result.tables_extracted = ingestion_result.tables_extracted
                    result.total_rows = ingestion_result.total_rows

                    if ingestion_result.tables_extracted > 0:
                        analyzer = get_data_analyzer()
                        analyzer.load_from_catalog()
                except Exception as e:
                    logger.warning(f"[FileRouter] PDF table extraction error: {e}")

    except Exception as e:
        result.error = str(e)
        logger.error(f"[FileRouter] Document processing error: {e}")

    return result


def _process_email(file_path: str) -> ProcessingResult:
    """Process an email file (EML, MSG) - parse, index body, extract notice, handle attachments."""
    from .email_parser import EmailParser
    from .document_rag import get_document_rag
    from .config import DOCUMENTS_DIR, TABLES_DIR, EMAILS_DIR

    result = ProcessingResult(success=False, file_path=file_path, file_type="email")
    filename = Path(file_path).name

    try:
        parser = EmailParser()
        parsed = parser.parse(file_path)

        # 1. Index email body into RAG (like a document)
        rag = get_document_rag()
        page_texts = parser.to_document_text(parsed)

        if page_texts:
            new_docs = rag.add_document_from_pages(
                file_path=file_path,
                page_texts=page_texts,
                metadata={"source_type": "email", "subject": parsed.subject},
            )
            if new_docs:
                rag.insert_documents(new_docs)

        # 2. Notice extraction from email body
        try:
            from .table_ingestion import extract_document_notice
            from .document_rag import generate_doc_id

            if page_texts:
                doc_id = generate_doc_id(file_path)
                notice_summary = extract_document_notice(
                    doc_id=doc_id,
                    file_path=file_path,
                    doc_text_by_page=page_texts,
                    use_llm=False,
                )
                if notice_summary:
                    result.notice_extracted = True
                    result.notice_summary = notice_summary
        except Exception as e:
            logger.warning(f"[FileRouter] Email notice extraction error: {e}")

        # 3. Process attachments recursively
        if parsed.attachments:
            att_dir = Path(EMAILS_DIR) / f"{Path(file_path).stem}_attachments"
            saved_paths = parser.save_attachments(parsed, att_dir)

            for att_path in saved_paths:
                att_ext = Path(att_path).suffix.lower()
                if att_ext in EXTENSION_MAP:
                    try:
                        att_result = route_file(att_path)
                        result.attachment_results.append({
                            "filename": Path(att_path).name,
                            "success": att_result.success,
                            "file_type": att_result.file_type,
                            "tables": att_result.tables_extracted,
                        })
                        if att_result.success:
                            result.attachments_processed += 1
                    except Exception as e:
                        logger.warning(f"[FileRouter] Attachment processing error: {e}")

        result.success = True
        logger.info(f"[FileRouter] Email processed: {filename}, "
                     f"attachments: {result.attachments_processed}")

    except Exception as e:
        result.error = str(e)
        logger.error(f"[FileRouter] Email processing error: {e}")

    return result


def _enrich_table_metadata(
    table_meta: "TableMetadata",
    df: pd.DataFrame,
    target_schema: str,
    file_path: str,
) -> None:
    """
    Extract search metadata from converted DataFrame.
    No LLM calls - pure pandas analysis.
    Populates description, semantic_tags, header_metadata on TableMetadata.
    """
    filename = Path(file_path).stem

    # --- 1. Date Range ---
    date_cols = [c for c in df.columns if "date" in c.lower()]
    period_parts = []
    for col in date_cols:
        dates = pd.to_datetime(df[col], errors="coerce").dropna()
        if not dates.empty:
            min_d, max_d = dates.min(), dates.max()
            if min_d.month == max_d.month and min_d.year == max_d.year:
                period_parts.append(f"{min_d.strftime('%B %Y')}")
            else:
                period_parts.append(
                    f"{min_d.strftime('%B %Y')} - {max_d.strftime('%B %Y')}"
                )

    # --- 2. Sheet names (multi-sheet IPC) ---
    sheet_names = []
    if "_sheet_name" in df.columns:
        sheet_names = df["_sheet_name"].dropna().unique().tolist()

    # --- 3. Schema-based tags ---
    SCHEMA_TAGS = {
        "equipment_log": [
            "equipment", "machinery", "deployment", "hours", "utilization",
        ],
        "ipc_sample": [
            "ipc", "progress", "boq", "quantities", "financial", "cumulative",
        ],
        "manpower_production": [
            "manpower", "workforce", "workers", "production", "labor",
        ],
    }
    tags = list(SCHEMA_TAGS.get(target_schema, []))

    # --- 4. Content-based tags ---
    for col_name in ["Block", "block"]:
        if col_name in df.columns:
            blocks = df[col_name].dropna().unique()[:5]
            tags.extend([f"block_{b}" for b in blocks if str(b).strip()])

    tags.append(target_schema.replace("_", " "))

    # --- 5. Header metadata ---
    header_meta = {
        "target_schema": target_schema,
        "source_file": filename,
        "row_count": str(len(df)),
    }
    if period_parts:
        header_meta["period"] = period_parts[0]
    if sheet_names:
        header_meta["sheets"] = ", ".join(str(s) for s in sheet_names[:6])

    # --- 6. Build description ---
    schema_names = {
        "equipment_log": "Equipment Log",
        "ipc_sample": "IPC (Interim Progress Certificate)",
        "manpower_production": "Manpower Production Log",
    }
    desc_parts = [schema_names.get(target_schema, target_schema)]
    if period_parts:
        desc_parts.append(period_parts[0])
    desc_parts.append(f"from {filename}")
    desc_parts.append(f"({len(df)} rows)")

    table_meta.description = " - ".join(desc_parts)
    table_meta.semantic_tags = tags
    table_meta.header_metadata = header_meta

    logger.info(
        f"[FileRouter] Enriched metadata: {table_meta.description}, "
        f"tags={len(tags)}"
    )


def _process_data_file(file_path: str) -> ProcessingResult:
    """
    Process a data file (Excel, CSV).
    Try format converter first, fallback to existing pipeline.
    """
    from .data_analyzer_sql import get_data_analyzer

    result = ProcessingResult(success=False, file_path=file_path, file_type="data")
    filename = Path(file_path).name

    # Step 1: Try format converter
    try:
        from .format_converter import get_format_converter

        converter = get_format_converter()
        conv_result = converter.process_excel(file_path)

        if conv_result and conv_result.success and conv_result.df is not None:
            # Converter succeeded - save as parquet and register
            from .catalog import get_catalog, TableMetadata

            catalog = get_catalog()
            entry = catalog.add_entry(file_path, "excel", ocr_decision="converter")

            table_id = catalog.generate_table_id(
                file_path, sheet_name=conv_result.target_schema
            )
            parquet_path = catalog.generate_parquet_path(table_id)
            conv_result.df.to_parquet(str(parquet_path), index=False)

            table_name = f"t_{table_id}"
            table_meta = TableMetadata(
                table_id=table_id,
                source_file=file_path,
                source_type="excel",
                table_name=table_name,
                parquet_path=str(parquet_path),
                sheet_name=conv_result.target_schema,
                row_count=len(conv_result.df),
                column_count=len(conv_result.df.columns),
                columns=list(conv_result.df.columns),
                extraction_method="converter",
            )

            # Enrich metadata for searchability
            _enrich_table_metadata(
                table_meta, conv_result.df,
                conv_result.target_schema or "", file_path,
            )

            catalog.add_table(entry, table_meta)

            # Load into DuckDB
            analyzer = get_data_analyzer()
            analyzer.load_from_catalog()

            result.success = True
            result.tables_extracted = 1
            result.total_rows = len(conv_result.df)
            result.converter_used = conv_result.converter_id
            result.converter_generated = conv_result.generated
            result.target_schema = conv_result.target_schema

            logger.info(f"[FileRouter] Data file converted: {filename} -> {conv_result.target_schema}")
            return result

    except Exception as e:
        logger.info(f"[FileRouter] Format converter skipped/failed for {filename}: {e}")

    # Step 2: Fallback to existing pipeline
    try:
        from .table_ingestion import ingest_file

        ingestion_result = ingest_file(file_path)
        result.tables_extracted = ingestion_result.tables_extracted
        result.total_rows = ingestion_result.total_rows

        if ingestion_result.tables_extracted > 0:
            analyzer = get_data_analyzer()
            analyzer.load_from_catalog()
            result.success = True
            logger.info(f"[FileRouter] Data file ingested via pipeline: {filename}")
        else:
            # Direct load fallback
            analyzer = get_data_analyzer()
            if analyzer.load_file(file_path):
                result.success = True
                result.tables_extracted = 1
                logger.info(f"[FileRouter] Data file loaded directly: {filename}")
            else:
                result.error = "No tables extracted and direct load failed"
    except Exception as e:
        # Last resort: direct load
        try:
            analyzer = get_data_analyzer()
            if analyzer.load_file(file_path):
                result.success = True
                result.tables_extracted = 1
                logger.info(f"[FileRouter] Data file loaded directly (after error): {filename}")
            else:
                result.error = str(e)
        except Exception as e2:
            result.error = str(e2)
            logger.error(f"[FileRouter] Data file processing failed: {e2}")

    return result
