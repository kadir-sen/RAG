"""FastAPI lifespan: startup sync replicating app.py lines 2262-2307."""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(_startup_sync)
    from backend.tasks.ingestion_jobs import start_ingestion_workers, stop_ingestion_workers
    from backend.tasks.report_jobs import start_report_workers, stop_report_workers
    from backend.tasks.forensic_jobs import start_forensic_workers, stop_forensic_workers
    start_ingestion_workers()
    start_report_workers()
    start_forensic_workers()
    try:
        yield
    finally:
        stop_ingestion_workers()
        stop_report_workers()
        stop_forensic_workers()


def _startup_sync():
    """Synchronous startup for Cloud Run (stateless — GCS is source of truth)."""

    # ── Step 1: Download ALL shared state from GCS FIRST ──
    # This MUST happen before loading any singletons.
    # Cloud Run instances are ephemeral — local disk may be stale or empty.
    print("[Startup] Syncing from GCS...")
    try:
        from src.gcs_storage import (
            sync_document_registry_from_gcs,
            sync_catalog_from_gcs,
            sync_all_parquets_from_gcs,
            sync_all_uploads_from_gcs,
            sync_user_conversations_from_gcs,
            sync_review_sessions_from_gcs,
        )
        sync_document_registry_from_gcs()  # Registry FIRST
        sync_catalog_from_gcs()
        sync_all_parquets_from_gcs()
        sync_all_uploads_from_gcs()
        sync_user_conversations_from_gcs("default")
        sync_review_sessions_from_gcs()
        print("[Startup] GCS sync complete")
    except Exception as e:
        print(f"[Startup] GCS sync error (non-fatal): {e}")

    # ── Step 1b: Repair JSON damaged by the old text-mode path normalizer ──
    # Until this release, config.normalize_stored_paths() rewrote every JSON file
    # under storage/ and data/ as raw text on every process start, turning each
    # backslash into "/" — which broke \" and left the file unparseable. Corrupt
    # conversations were then delisted the moment someone opened one. That, not
    # any storage loss, is what "history resets on deploy" was.
    #
    # The repair only ever turns a "/" back into a "\", is accepted only when the
    # result parses AND is a length-preserving slash-only inverse of the input,
    # keeps the original as <name>.corrupt.bak, and leaves anything it cannot
    # verify exactly as it found it. Marker-gated, so a healthy boot costs a stat.
    # Non-fatal by design: a migration that blocks startup is worse than the
    # damage it repairs.
    try:
        import os
        from src.config import DATA_DIR, STORAGE_DIR
        from src.json_repair import run_escape_repair_migration
        result = run_escape_repair_migration(
            roots=(STORAGE_DIR, DATA_DIR),
            marker_dir=STORAGE_DIR,
            force=os.getenv("REPAIR_JSON_FORCE", "").lower() in ("1", "true", "yes"),
            restore_content_escapes=os.getenv(
                "REPAIR_JSON_CONTENT", "true").lower() in ("1", "true", "yes"),
        )
        if result:
            print(f"[Startup] JSON repair: {result['repaired']} repaired, "
                  f"{result['ok']} intact, {result['unrepairable']} unrepairable")
    except Exception as e:
        print(f"[Startup] JSON repair migration failed (non-fatal): {e}")

    # ── Step 1c: Re-list conversations that were delisted while corrupt ──
    # Repairing a file does not make it visible again: nothing in the UI can
    # reach a conversation id that is not in its user's index.
    try:
        from src.config import CONVERSATIONS_DIR
        from src.conversation_store import ConversationStore
        total = 0
        if CONVERSATIONS_DIR.exists():
            for user_dir in sorted(p for p in CONVERSATIONS_DIR.iterdir() if p.is_dir()):
                total += ConversationStore(user_dir.name).adopt_orphans()
        if total:
            print(f"[Startup] Re-listed {total} orphaned conversation(s)")
    except Exception as e:
        print(f"[Startup] Orphan adoption failed (non-fatal): {e}")

    # ── Step 2: Load document registry from disk (just synced from GCS) ──
    try:
        from src.document_registry import get_document_registry
        registry = get_document_registry()
        count = len(registry.get_all())
        print(f"[Startup] Document registry: {count} documents")
    except Exception as e:
        print(f"[Startup] Registry load: {e}")

    # ── Step 3: Load vector store (Pinecone or Qdrant) ──
    try:
        from src.document_rag import get_document_rag
        rag = get_document_rag()
        if rag.backend == "qdrant":
            from src.config import QDRANT_COLLECTION
            try:
                info = rag.qdrant_client.get_collection(QDRANT_COLLECTION)
                vec_count = info.points_count or 0
            except Exception:
                vec_count = 0
        else:
            stats = rag.pinecone_index.describe_index_stats()
            vec_count = stats.get("total_vector_count", 0)
        if vec_count > 0 and not rag.index:
            rag.load_index()
            print(f"[Startup] Loaded {vec_count} vectors from {rag.backend}")
        # Reconcile durable per-project vector readiness after restarts and
        # migrations. Orphan points have no project_id and are intentionally
        # excluded from every project count.
        from src.project_store import get_project_store
        project_store = get_project_store()
        for project in project_store.list_all():
            project_id = project["project_id"]
            point_count = rag.count_project_points(project_id)
            current = project_store.get_vector_state(project_id)
            if point_count > 0:
                project_store.set_vector_state(
                    project_id, "ready", point_count=point_count,
                )
            elif current.get("status") not in ("provisioning", "indexing", "error"):
                project_store.set_vector_state(
                    project_id, "empty", point_count=0,
                )
    except Exception as e:
        print(f"[Startup] Vector store sync: {e}")

    # ── Step 4: Reload DuckDB tables from catalog (freshly synced parquets) ──
    try:
        from src.data_analyzer_sql import get_data_analyzer
        analyzer = get_data_analyzer()
        loaded = analyzer.load_from_catalog()
        if loaded > 0:
            print(f"[Startup] Loaded {loaded} tables into DuckDB")
    except Exception as e:
        print(f"[Startup] Catalog reload: {e}")

    # ── Step 5: Rebuild light graph from notices ──
    try:
        from src.light_graph import get_light_graph
        graph = get_light_graph()
        if not graph.graph.nodes:
            graph.rebuild_from_notices()
            if graph.graph.nodes:
                print(f"[Startup] Rebuilt graph: {len(graph.graph.nodes)} notices")
    except Exception as e:
        print(f"[Startup] Graph rebuild: {e}")

    # ── Step 6: Hydrate registry from RAG + catalog (backfill only) ──
    try:
        from src.document_registry import get_document_registry
        from src.document_rag import get_document_rag
        from src.catalog import get_catalog
        registry = get_document_registry()
        rag_registry = get_document_rag().file_registry
        catalog_entries = get_catalog().entries
        added = registry.hydrate_from_existing(rag_registry, catalog_entries)
        if added:
            print(f"[Startup] Hydrated {added} new documents into registry")
    except Exception as e:
        print(f"[Startup] Registry hydration: {e}")

    # ── Step 7: Recover legacy files left mid-index by an older deployment ──
    # New uploads already live in the durable ingestion_jobs queue. This pass
    # only adopts old registry records that predate it.
    try:
        from pathlib import Path
        from src.document_registry import get_document_registry
        from backend.tasks.ingestion_jobs import get_ingestion_job_store

        registry = get_document_registry()
        stuck = [r for r in registry.get_all() if r.status in ("processing", "error")]
        requeued = 0
        for rec in stuck:
            fp = getattr(rec, "file_path", "")
            if not fp or not Path(fp).exists():
                continue  # vectors-only / missing file → can't re-index, leave as-is
            project_id = getattr(rec, "project_id", "") or ""
            if not project_id:
                continue
            get_ingestion_job_store().enqueue(project_id, rec.doc_id, fp, rec.file_name)
            requeued += 1
        if requeued:
            print(f"[Startup] Re-queued {requeued} stuck file(s) for indexing")
    except Exception as e:
        print(f"[Startup] Stuck-file recovery: {e}")
