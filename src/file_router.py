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
    # Per-sheet schema match diagnostics for Excel/CSV (one entry per sheet attempted)
    # Each: {sheet, schema_id, ratio, matched_columns, missing_columns, registered}
    schema_match_details: List[Dict[str, Any]] = field(default_factory=list)


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
        # Topic clustering assignment — fire-and-forget; needs the freshly
        # upserted chunks in Pinecone, which is why we run it after
        # mark_completed and off the request thread. Data-only files don't
        # produce embeddings so we skip them.
        if file_type in ("document", "email"):
            try:
                import threading as _t
                from .document_clusterer import get_clusterer
                _t.Thread(
                    target=lambda: get_clusterer().assign_new_doc(doc_id),
                    daemon=True,
                ).start()
            except Exception as ce:
                logger.warning(f"[FileRouter] Clusterer hook failed: {ce}")
    elif result.error:
        registry.mark_error(doc_id, result.error)

    return result


def _enrich_document_llm(file_path: str, full_text: str,
                         notice_summary: Optional[dict] = None,
                         set_scope_payload: bool = True) -> None:
    """Generate a one-line summary + 3-5 topic tags for a document at ingest time.

    Phase 2 enrichment: a single cheap, cached LLM call over the first ~2k chars.
    Stored on the registry record (llm_summary / llm_topics) and later fed to the
    LLM router's document-topic context to reduce misrouting/hallucination.

    Beyond routing, the same call's structured outputs are wired live at ingest:
      - events[]   → event_timeline store (chronological/excuse questions)
      - doc_type   → vector payload scope (scoped retrieval filters)
      - date       → vector payload scope (from the already-extracted notice)
    Failures are non-fatal — ingest must never break because enrichment failed.
    """
    text = (full_text or "").strip()
    if len(text) < 80:
        return  # too little signal to summarize meaningfully

    try:
        import hashlib
        from . import llm_client
        from .document_rag import generate_doc_id, get_document_rag
        from .document_registry import get_document_registry

        # One unified, cheap call returns everything the downstream layers need:
        # routing summary/topics + a construction doc_type (classification) + any
        # timeline events (delay/disruption/excuse/decision/milestone) + domain
        # terms learned from the text. The first ~4k chars are enough to classify
        # and catch the lead events/definitions without reading the whole document.
        snippet = text[:4000]
        prompt = (
            "You index construction-project / public-inquiry documents.\n"
            "From the excerpt, return ONE compact JSON object with these keys:\n"
            '{\n'
            '  "summary": "<one sentence, max 160 chars>",\n'
            '  "topics": ["<3-5 short tags, e.g. \'delay notice\', \'BOQ\'>"],\n'
            '  "doc_type": "<one of: correspondence, contract, variation, claim, '
            'delay notice, payment certificate, BOQ, drawing, report, meeting minutes, '
            'witness statement, transcript, other>",\n'
            '  "events": [{"type": "<delay|disruption|excuse|decision|milestone|claim>", '
            '"date": "<as written or empty>", "actor": "<who, or empty>", '
            '"description": "<short>"}],\n'
            '  "new_terms": [{"term": "<acronym/jargon>", "definition": "<expansion as '
            'stated in the text>"}]\n'
            '}\n'
            "Use [] when a list has nothing. Output JSON only.\n\n"
            f"DOCUMENT EXCERPT:\n{snippet}"
        )
        cache_key = "docenrich2:" + hashlib.sha256(snippet.encode()).hexdigest()[:32]
        resp = llm_client.generate_json(
            prompt,
            system="You are a precise construction-document indexer. Output JSON only.",
            cache_key=cache_key,
        )
        data = resp.raw if isinstance(resp.raw, dict) else {}
        summary = str(data.get("summary", "")).strip()[:300] or None
        topics = [str(t).strip() for t in (data.get("topics") or []) if str(t).strip()][:5]
        doc_type = str(data.get("doc_type", "")).strip()[:60]

        if summary or topics:
            get_document_registry().set_llm_enrichment(
                generate_doc_id(file_path),
                summary=summary,
                topics=topics or None,
            )

        # Persist the structured outputs (doc_type, events, new_terms) to a side
        # store for the Faz-2 batch passes (event-timeline + learning jargon) to
        # consume. Kept separate so this stays a single cheap call per document.
        events = [e for e in (data.get("events") or []) if isinstance(e, dict)]
        new_terms = [t for t in (data.get("new_terms") or []) if isinstance(t, dict)]
        doc_id = generate_doc_id(file_path)
        file_name = Path(file_path).name
        if doc_type or events or new_terms:
            _save_doc_enrichment(file_path, {
                "doc_id": doc_id,
                "file_name": file_name,
                "doc_type": doc_type,
                "summary": summary or "",
                "topics": topics,
                "events": events,
                "new_terms": new_terms,
            })

        # ── Wire the structured outputs LIVE (was previously written-then-ignored) ──
        # 1) events → chronological store, straight from ingest (no offline script).
        _persist_events_to_timeline(doc_id, file_name, project="", events=events)

        # 1b) new_terms → jargon dictionary (auto onboarding, feedback-free).
        _learn_jargon_from_terms(new_terms)

        # 2) doc_type + document date → vector payload, so scoped retrieval filters
        #    have something to match. Date comes from the notice already extracted
        #    upstream (no new parsing). Empty values are dropped by update_payload_scope.
        doc_date = ""
        if isinstance(notice_summary, dict):
            doc_date = str(notice_summary.get("date") or "").strip()
        # Per-doc payload write is fine for single uploads but too slow for a
        # bulk backfill (one filtered set_payload per doc) — bulk runs disable it
        # and use the dedicated scripts/enrich_payload.py (which indexes first).
        scope = {"doc_type": doc_type, "date": doc_date}
        if set_scope_payload and any(scope.values()):
            try:
                get_document_rag().update_payload_scope(file_name, scope)
            except Exception as e:
                logger.debug(f"[FileRouter] scope payload skipped: {e}")
    except Exception as e:
        logger.warning(f"[FileRouter] LLM document enrichment skipped: {e}")


def _save_doc_enrichment(file_path: str, payload: dict) -> None:
    """Write the structured enrichment for one document to storage/enrichment/.
    Best-effort; consumed later by the Faz-2 event-timeline and jargon passes."""
    try:
        import json
        from .config import STORAGE_DIR
        out_dir = Path(STORAGE_DIR) / "enrichment"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{payload['doc_id']}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"[FileRouter] enrichment save skipped: {e}")


def _persist_events_to_timeline(doc_id: str, file_name: str, project: str,
                                events: list) -> None:
    """Load a document's enrichment events straight into the event-timeline store
    at ingest, so chronological questions work without the offline batch script.
    Mirrors the mapping in scripts/build_event_timeline.py. Idempotent (stable
    event ids) and non-fatal — ingest must never break on this."""
    if not events:
        return
    try:
        from .event_timeline import get_event_timeline
        rows = []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            rows.append({
                "doc_id": doc_id,
                "file_name": file_name,
                "project": project or "",
                "date": ev.get("date", ""),
                "event_type": ev.get("type", ""),
                "actor": ev.get("actor", ""),
                "reason": ev.get("reason", "") or ev.get("description", ""),
                "severity": ev.get("severity", ""),
                "status": ev.get("status", ""),
                "description": ev.get("description", ""),
                "source": "ingest",
            })
        get_event_timeline().add_events(rows)
    except Exception as e:
        logger.warning(f"[FileRouter] event timeline persist skipped: {e}")


def _learn_jargon_from_terms(new_terms: list) -> None:
    """Feed acronyms/jargon the enrichment mined from a document straight into the
    jargon dictionary, so a new client's vocabulary self-populates at ingest (no
    manual entry, no 👍 feedback needed). Built-ins/dupes raise and are skipped —
    same posture as flywheel._learn_jargon."""
    if not new_terms:
        return
    try:
        from .jargon_manager import get_jargon_manager
        jm = get_jargon_manager()
        for t in new_terms:
            if not isinstance(t, dict):
                continue
            term = str(t.get("term", "")).strip()
            definition = str(t.get("definition", "")).strip().rstrip(".").strip()
            if not term or len(definition) < 3:
                continue
            try:
                jm.add_custom_term(term, definition)
                logger.info(f"[FileRouter] learned jargon: {term} → {definition}")
            except Exception:
                pass  # built-in or duplicate — skip silently
    except Exception as e:
        logger.warning(f"[FileRouter] jargon learning skipped: {e}")


def _process_document(file_path: str) -> ProcessingResult:
    """Process a document file (PDF, DOCX, TXT) through RAG pipeline."""
    from .document_rag import get_document_rag
    from .data_analyzer_sql import get_data_analyzer

    result = ProcessingResult(success=False, file_path=file_path, file_type="document")
    filename = Path(file_path).name

    try:
        from backend.tasks.progress import report
    except Exception:
        def report(*_a, **_k):  # ingest run outside the API (scripts) → no-op
            pass

    try:
        rag = get_document_rag()
        report("extracting", 0.10)          # OCR / text extraction (slowest stage for scans)
        new_docs = rag.add_document(file_path)

        if new_docs:
            report("embedding", 0.55)        # chunk + local embed + Qdrant upsert + lexical
            rag.insert_documents(new_docs)
            result.success = True
            report("searchable", 0.78)       # ← document is now queryable; tail is enrichment only

            # OCR stats
            file_info = rag.file_registry.get(filename, {})
            result.ocr_pages = file_info.get("ocr_pages", 0)

            # Notice extraction
            doc_text_by_page = {}
            try:
                from .table_ingestion import extract_document_notice
                from .document_rag import generate_doc_id

                for doc in rag.documents:
                    if doc.metadata.get("file_name") == filename:
                        page_num = doc.metadata.get("page_number", 1)
                        doc_text_by_page[page_num] = doc.text

                from .config import INGEST_EXTRACT_NOTICES
                if doc_text_by_page and INGEST_EXTRACT_NOTICES:
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
            doc_full_text = ""
            if doc_text_by_page:
                doc_full_text = "\n".join(
                    doc_text_by_page[p] for p in sorted(doc_text_by_page.keys())
                ).strip()
            if doc_full_text and result.notice_summary:
                result.notice_summary["summary"] = (
                    doc_full_text[:200].strip() + "..." if len(doc_full_text) > 200 else doc_full_text
                )

            # LLM enrichment (Phase 2): one-line summary + topic tags for routing,
            # plus live event-timeline + scoped-payload wiring (uses the notice date).
            report("enriching", 0.88)
            _enrich_document_llm(file_path, doc_full_text,
                                 notice_summary=result.notice_summary)

            # Table extraction for PDFs (direct — skips duplicate OCR analysis).
            # Gated: skip on fast bulk embedding runs (INGEST_EXTRACT_TABLES=false).
            from .config import INGEST_EXTRACT_TABLES
            if INGEST_EXTRACT_TABLES and filename.lower().endswith(".pdf"):
                report("tables", 0.95)
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
        email_full_text = ""
        if page_texts:
            email_full_text = "\n".join(
                page_texts[p] for p in sorted(page_texts.keys())
            ).strip()
        if email_full_text and result.notice_summary:
            result.notice_summary["summary"] = (
                email_full_text[:200].strip() + "..." if len(email_full_text) > 200 else email_full_text
            )

        # 2d. LLM enrichment (Phase 2): one-line summary + topic tags for routing
        _enrich_document_llm(file_path, email_full_text)

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

    # --- 7. Column jargon expansions (per-table glossary) ---
    try:
        from .jargon_manager import get_jargon_manager
        jm = get_jargon_manager()
        col_jargon = dict(table_meta.column_jargon or {})
        for col in table_meta.columns:
            if col in col_jargon:
                continue
            _, expanded = jm.normalize_column_name(col)
            if expanded:
                col_jargon[col] = expanded
        if col_jargon:
            table_meta.column_jargon = col_jargon
    except Exception as je:
        logger.debug(f"[FileRouter] column_jargon enrichment skipped: {je}")

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

                result.schema_match_details.append({
                    "sheet": conv_result.sheet_name,
                    "schema_id": conv_result.target_schema,
                    "table_name": table_name,
                    "rows": len(conv_result.df),
                    "registered": True,
                })

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

    # 6. Cluster bookkeeping
    try:
        from .document_clusterer import get_clusterer
        get_clusterer().forget_doc(doc_id)
        result["cluster_cleaned"] = True
    except Exception as e:
        logger.warning(f"[Delete] Cluster cleanup failed: {e}")

    # 7. Registry record (last — after all cleanup)
    registry.delete(doc_id)
    result["registry_cleaned"] = True

    logger.info(f"[Delete] Document deleted: {record.file_name} ({doc_id})")
    return result
