"""FastAPI lifespan: startup sync replicating app.py lines 2262-2307."""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(_startup_sync)
    yield


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

    # ── Step 2: Load document registry from disk (just synced from GCS) ──
    try:
        from src.document_registry import get_document_registry
        registry = get_document_registry()
        count = len(registry.get_all())
        print(f"[Startup] Document registry: {count} documents")
    except Exception as e:
        print(f"[Startup] Registry load: {e}")

    # ── Step 3: Load Pinecone vectors ──
    try:
        from src.document_rag import get_document_rag
        rag = get_document_rag()
        stats = rag.pinecone_index.describe_index_stats()
        vec_count = stats.get("total_vector_count", 0)
        if vec_count > 0 and not rag.index:
            rag.load_index()
            print(f"[Startup] Loaded {vec_count} vectors from Pinecone")
    except Exception as e:
        print(f"[Startup] Pinecone sync: {e}")

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
