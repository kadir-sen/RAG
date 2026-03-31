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
from .table_normalizer import parse_mixed_datetime


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

    # Register in document registry for tracking
    from .document_registry import get_document_registry
    from .document_rag import generate_doc_id
    registry = get_document_registry()
    try:
        file_size_kb = Path(file_path).stat().st_size // 1024
    except OSError:
        file_size_kb = 0
    record = registry.register(
        file_name=Path(file_path).name,
        file_path=file_path,
        file_size_kb=file_size_kb,
        file_type=file_type,
        extension=ext,
    )
    doc_id = record.doc_id

    if file_type == "document":
        result = _process_document(file_path)
    elif file_type == "email":
        result = _process_email(file_path)
    elif file_type == "data":
        result = _process_data_file(file_path)
    else:
        result = ProcessingResult(
            success=False,
            file_path=file_path,
            file_type="unknown",
            error=f"Unsupported file type: {ext}",
        )

    # Update registry with result
    if result.success:
        table_names = []
        if hasattr(result, 'converter_used') and result.converter_used:
            table_names.append(result.converter_used)
        registry.mark_completed(
            doc_id,
            table_names=table_names,
            notice_extracted=result.notice_extracted,
        )
    elif result.error:
        registry.mark_error(doc_id, result.error)

    return result


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

            # Quick truncation summary (no LLM — fast)
            if doc_text_by_page and result.notice_summary:
                full_text = "\n".join(
                    doc_text_by_page[p] for p in sorted(doc_text_by_page.keys())
                ).strip()
                if full_text:
                    result.notice_summary["summary"] = (
                        full_text[:200].strip() + "..." if len(full_text) > 200 else full_text
                    )

            # Table extraction for PDFs (direct — skips duplicate OCR analysis)
            if filename.lower().endswith(".pdf"):
                try:
                    from .pdf_table_extractor import extract_pdf_tables
                    tables = extract_pdf_tables(file_path, save_parquet=True)
                    result.tables_extracted = len(tables)
                    result.total_rows = sum(
                        getattr(t, "row_count", 0) for t in tables
                    )

                    if result.tables_extracted > 0:
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

        # 2b. Enrich notice with email parser metadata (sender/recipient/cc)
        if result.notice_summary and parsed:
            ns = result.notice_summary
            if not ns.get("sender") and parsed.sender:
                ns["sender"] = parsed.sender
            if not ns.get("recipient") and parsed.recipients:
                ns["recipient"] = ", ".join(parsed.recipients)
            if not ns.get("cc_list") and parsed.cc:
                ns["cc_list"] = parsed.cc

        # 2c. Quick truncation summary (no LLM — fast)
        if page_texts and result.notice_summary:
            full_text = "\n".join(
                page_texts[p] for p in sorted(page_texts.keys())
            ).strip()
            if full_text:
                result.notice_summary["summary"] = (
                    full_text[:200].strip() + "..." if len(full_text) > 200 else full_text
                )

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
        dates = parse_mixed_datetime(df[col]).dropna()
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
    Format converter validates against known schemas (no LLM).
    Multi-sheet files (e.g. IPC) produce multiple tables.
    Fallback to raw ingestion if no schema matches.
    """
    from .data_analyzer_sql import get_data_analyzer

    result = ProcessingResult(success=False, file_path=file_path, file_type="data")
    filename = Path(file_path).name

    # Step 1: Try format converter (direct schema validation, no LLM)
    try:
        from .schema_converter import get_format_converter

        converter = get_format_converter()
        conv_results = converter.process_excel(file_path)

        if conv_results:
            from .catalog import get_catalog, TableMetadata

            catalog = get_catalog()
            entry = catalog.add_entry(file_path, "excel", ocr_decision="direct")
            tables_saved = 0
            total_rows = 0
            ipc_table_names = []  # Track IPC tables for unified view

            for conv_result in conv_results:
                if not conv_result.success or conv_result.df is None:
                    continue

                # Use sheet_name for multi-sheet, target_schema for single
                sheet_label = conv_result.sheet_name or conv_result.target_schema
                table_id = catalog.generate_table_id(
                    file_path, sheet_name=sheet_label,
                    target_schema=conv_result.target_schema,
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
                    sheet_name=sheet_label,
                    row_count=len(conv_result.df),
                    column_count=len(conv_result.df.columns),
                    columns=list(conv_result.df.columns),
                    extraction_method="direct_schema",
                )

                # Enrich metadata for searchability
                _enrich_table_metadata(
                    table_meta, conv_result.df,
                    conv_result.target_schema or "", file_path,
                )

                # Extract table insight (pandas-based, no LLM)
                try:
                    from .table_insight_extractor import extract_table_insight
                    insight = extract_table_insight(
                        conv_result.df, file_path,
                        conv_result.target_schema or "",
                    )
                    table_meta.insight = insight
                except Exception as ie:
                    logger.warning(f"[FileRouter] Insight extraction error: {ie}")

                # Table summary (pandas-based, no LLM)
                try:
                    from .content_generator import summarize_table
                    table_meta.summary = summarize_table(
                        conv_result.df, conv_result.target_schema or "", filename,
                    )
                except Exception as se:
                    logger.warning(f"[FileRouter] Table summary error: {se}")

                catalog.add_table(entry, table_meta)
                tables_saved += 1
                total_rows += len(conv_result.df)
                if conv_result.target_schema == "ipc_sample":
                    ipc_table_names.append(table_name)

            if tables_saved > 0:
                # Load all tables into DuckDB
                analyzer = get_data_analyzer()
                analyzer.load_from_catalog()

                # Create unified view for multi-sheet IPC files
                if len(ipc_table_names) > 1:
                    try:
                        analyzer.create_ipc_unified_view(ipc_table_names)
                        logger.info(f"[FileRouter] IPC unified view created from "
                                    f"{len(ipc_table_names)} sheets")
                    except Exception as ue:
                        logger.warning(f"[FileRouter] IPC unified view failed: {ue}")

                result.success = True
                result.tables_extracted = tables_saved
                result.total_rows = total_rows
                result.converter_used = conv_results[0].converter_id
                result.target_schema = conv_results[0].target_schema

                logger.info(f"[FileRouter] Data file processed: {filename} "
                            f"-> {tables_saved} tables, {total_rows} rows")
                return result

    except Exception as e:
        logger.info(f"[FileRouter] Format converter skipped/failed for {filename}: {e}")

    # Step 2: Fallback — direct Excel extraction (no OCR, no TableIngestionPipeline)
    try:
        from .excel_table_extractor import extract_excel_tables
        from .catalog import get_catalog

        metadata_list = extract_excel_tables(file_path, save_parquet=True)
        if metadata_list:
            catalog = get_catalog()
            tables_saved = len(metadata_list)
            total_rows = sum(m.row_count for m in metadata_list)

            analyzer = get_data_analyzer()
            analyzer.load_from_catalog()
            result.success = True
            result.tables_extracted = tables_saved
            result.total_rows = total_rows
            logger.info(f"[FileRouter] Data file extracted directly: {filename} "
                        f"-> {tables_saved} tables, {total_rows} rows")
        else:
            # Last resort: direct pandas load into DuckDB
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


def delete_document(doc_id: str) -> Dict[str, Any]:
    """Delete a document from all stores (registry, DuckDB, catalog, RAG, notices, disk).

    Returns a summary dict of what was cleaned up.
    """
    from .document_registry import get_document_registry

    registry = get_document_registry()
    record = registry.get(doc_id)
    if not record:
        return {"error": "Document not found", "doc_id": doc_id}

    result: Dict[str, Any] = {"doc_id": doc_id, "file_name": record.file_name}

    # 1. DuckDB tables
    if record.table_names:
        try:
            from .data_analyzer_sql import get_data_analyzer
            analyzer = get_data_analyzer()
            result["tables_dropped"] = analyzer.drop_tables(record.table_names)
        except Exception as e:
            logger.warning(f"[Delete] DuckDB cleanup failed: {e}")

    # 2. Catalog + Parquet files
    try:
        from .catalog import get_catalog
        get_catalog().remove_entry(record.file_path)
        result["catalog_cleaned"] = True
    except Exception as e:
        logger.warning(f"[Delete] Catalog cleanup failed: {e}")

    # 3. RAG / Pinecone vectors
    try:
        from .document_rag import get_document_rag
        get_document_rag().clear_file(record.file_name)
        result["rag_cleaned"] = True
    except Exception as e:
        logger.warning(f"[Delete] RAG cleanup failed: {e}")

    # 4. Notice JSON
    try:
        from .notice_extractor import get_notice_extractor
        extractor = get_notice_extractor()
        if extractor.delete_notice(doc_id):
            result["notice_cleaned"] = True
    except Exception as e:
        logger.warning(f"[Delete] Notice cleanup failed: {e}")

    # 5. Source file on disk + GCS
    try:
        fp = Path(record.file_path)
        if fp.exists():
            fp.unlink()
            result["file_deleted"] = True
            logger.info(f"[Delete] Removed file: {fp}")
        from .gcs_storage import delete_uploaded_file_from_gcs
        delete_uploaded_file_from_gcs(record.file_path)
    except Exception as e:
        logger.warning(f"[Delete] Disk cleanup failed: {e}")

    # 6. Registry record (last — after all cleanup)
    registry.delete(doc_id)
    result["registry_cleaned"] = True

    logger.info(f"[Delete] Document deleted: {record.file_name} ({doc_id})")
    return result
