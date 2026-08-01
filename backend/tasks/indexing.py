"""Background file indexing — wraps existing src/file_router.route_file()."""

import threading
from pathlib import Path
from backend.tasks.progress import indexing_progress, current_file_var, current_job_var, report

# Cap concurrent heavy indexing jobs (OCR + embedding) so a batch of uploads
# doesn't exhaust CPU/RAM on a small box. Extra files block here and show
# "queued" until a slot frees.
from src.config import INGEST_MAX_CONCURRENCY
_INGEST_SEM = threading.BoundedSemaphore(max(1, INGEST_MAX_CONCURRENCY))


def index_file_background(file_id: str, file_path: str, corpus: str = "",
                          project_id: str = "", job_id: str = ""):
    """Run as FastAPI BackgroundTask."""
    from src.file_router import route_file
    from src.document_registry import get_document_registry

    registry = get_document_registry()
    indexing_progress.start(file_id, Path(file_path).name)
    # Stamp this thread so the deep ingest code can report granular progress.
    current_file_var.set(file_id)
    current_job_var.set(job_id)
    if project_id:
        from src.project_context import set_current_project
        set_current_project(project_id, "editor")
    # Tag any data tables produced by this ingest with the uploader's corpus
    # (background tasks don't inherit the request ContextVar, so set it here).
    if corpus:
        try:
            from src.document_rag import corpus_var
            corpus_var.set(corpus.lower())
        except Exception:
            pass

    # Wait for a concurrency slot (shows "queued" while others index).
    if not _INGEST_SEM.acquire(blocking=False):
        report("queued", 0.02)
        _INGEST_SEM.acquire()
    try:
        from src.document_rag import get_document_rag
        from src.project_store import get_project_store
        project_store = get_project_store()
        vector_state = project_store.get_vector_state(project_id)
        profile = str(vector_state.get("embedding_profile") or "local-bge-v1")
        rag = get_document_rag()
        existing_points = rag.ensure_project_partition(project_id, profile)
        project_store.set_vector_state(
            project_id, "indexing", point_count=existing_points,
        )

        result = route_file(
            file_path, project_id=project_id, file_id=file_id,
        )

        # Determine data_table_status only for Excel/CSV files
        data_table_status: str | None = None
        if result.file_type == "data":
            if result.success and result.tables_extracted > 0:
                data_table_status = "registered"
            elif result.success and result.tables_extracted == 0:
                data_table_status = "no_schema_match"
            else:
                data_table_status = "error"

        if result.success:
            report("indexing", 0.96)
            completion_details = {
                "file_type": result.file_type,
                "ocr_pages": result.ocr_pages,
                "tables_extracted": result.tables_extracted,
                "total_rows": result.total_rows,
                "notice_extracted": result.notice_extracted,
                "attachments": result.attachments_processed,
                "data_table_status": data_table_status,
            }
            indexing_progress.complete(file_id, details=completion_details)
            # Update document registry
            table_names = getattr(result, "table_names", []) or []
            registry.mark_completed(
                file_id,
                table_names=table_names,
                notice_extracted=result.notice_extracted,
                data_table_status=data_table_status,
                data_tables_count=result.tables_extracted if result.file_type == "data" else None,
                schema_match_details=(
                    result.schema_match_details if result.file_type == "data" else None
                ),
            )
            if job_id:
                from backend.tasks.ingestion_jobs import get_ingestion_job_store
                get_ingestion_job_store().complete(job_id, completion_details)
            point_count = rag.count_project_points(project_id)
            project_store.set_vector_state(
                project_id,
                "ready" if point_count > 0 else "provisioned",
                point_count=point_count,
            )
        else:
            error = result.error or "Unknown error"
            indexing_progress.fail(file_id, error)
            registry.mark_error(file_id, error)
            if job_id:
                from backend.tasks.ingestion_jobs import get_ingestion_job_store
                get_ingestion_job_store().fail(job_id, error)
            project_store.set_vector_state(project_id, "error", last_error=error)
            if data_table_status:
                # Even on failure, record status for data files so the UI can flag them
                with registry._file_lock:
                    rec = registry._records.get(file_id)
                    if rec:
                        rec.data_table_status = data_table_status
                        registry._save()
    except Exception as e:
        indexing_progress.fail(file_id, str(e))
        registry.mark_error(file_id, str(e))
        if job_id:
            from backend.tasks.ingestion_jobs import get_ingestion_job_store
            get_ingestion_job_store().fail(job_id, str(e))
        try:
            from src.project_store import get_project_store
            get_project_store().set_vector_state(
                project_id, "error", last_error=str(e),
            )
        except Exception:
            pass
    finally:
        try:
            _INGEST_SEM.release()
        except Exception:
            pass
        # Ensure all data is persisted to GCS before background task ends
        # (Cloud Run may kill the instance after this task completes)
        try:
            from src.gcs_storage import sync_catalog_to_gcs, sync_document_registry_to_gcs
            sync_document_registry_to_gcs()
            sync_catalog_to_gcs()
        except Exception:
            pass
