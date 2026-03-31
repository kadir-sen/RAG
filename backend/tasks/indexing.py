"""Background file indexing — wraps existing src/file_router.route_file()."""

from pathlib import Path
from backend.tasks.progress import indexing_progress


def index_file_background(file_id: str, file_path: str):
    """Run as FastAPI BackgroundTask."""
    from src.file_router import route_file
    from src.document_registry import get_document_registry

    registry = get_document_registry()
    indexing_progress.start(file_id, Path(file_path).name)

    try:
        result = route_file(file_path)

        if result.success:
            indexing_progress.complete(file_id, details={
                "file_type": result.file_type,
                "ocr_pages": result.ocr_pages,
                "tables_extracted": result.tables_extracted,
                "total_rows": result.total_rows,
                "notice_extracted": result.notice_extracted,
                "attachments": result.attachments_processed,
            })
            # Update document registry
            table_names = getattr(result, "table_names", []) or []
            registry.mark_completed(
                file_id,
                table_names=table_names,
                notice_extracted=result.notice_extracted,
            )
        else:
            error = result.error or "Unknown error"
            indexing_progress.fail(file_id, error)
            registry.mark_error(file_id, error)
    except Exception as e:
        indexing_progress.fail(file_id, str(e))
        registry.mark_error(file_id, str(e))
    finally:
        # Ensure all data is persisted to GCS before background task ends
        # (Cloud Run may kill the instance after this task completes)
        try:
            from src.gcs_storage import sync_catalog_to_gcs, sync_document_registry_to_gcs
            sync_document_registry_to_gcs()
            sync_catalog_to_gcs()
        except Exception:
            pass
