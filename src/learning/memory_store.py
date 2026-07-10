"""Shared persistence primitive for the learning layer.

A DuckDB singleton at storage/learning/learning.db, mirroring interaction_log.
All writes are best-effort and must never break a live query. Later sprints add
document_memory / schema_memory / query_patterns tables alongside workflow_runs.
"""

from __future__ import annotations

import threading
from typing import Optional

import duckdb

from ..config import STORAGE_DIR
from ..logger import logger

LEARNING_DIR = STORAGE_DIR / "learning"
LEARNING_DB = LEARNING_DIR / "learning.db"


class MemoryStore:
    """Singleton DuckDB connection for learning-layer tables."""

    _instance: Optional["MemoryStore"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._db_lock = threading.RLock()
                    inst._con = None
                    inst._init_db()
                    cls._instance = inst
        return cls._instance

    def _init_db(self):
        LEARNING_DIR.mkdir(parents=True, exist_ok=True)
        try:
            self._con = duckdb.connect(str(LEARNING_DB))
        except Exception as e:
            logger.error(f"[MemoryStore] init failed ({e}); in-memory fallback")
            self._con = duckdb.connect(":memory:")
        self._con.execute(
            "CREATE TABLE IF NOT EXISTS workflow_runs ("
            "run_id VARCHAR PRIMARY KEY, ts VARCHAR, corpus VARCHAR, "
            "project_id VARCHAR, username VARCHAR, user_query VARCHAR, "
            "query_signature VARCHAR, workflow_id VARCHAR, status VARCHAR, "
            "source VARCHAR, selected_xer VARCHAR, selected_excel_tables VARCHAR, "
            "selected_documents VARCHAR, selected_inputs_summary VARCHAR, "
            "fallback_reason VARCHAR, caveats VARCHAR, output_block_types VARCHAR, "
            "analyst_review_required BOOLEAN, latency_ms DOUBLE, "
            "user_feedback VARCHAR)"
        )
        # Delay-claim candidate events with an analyst lifecycle
        # (candidate → confirmed | rejected | merged). Kept separate from the
        # enrichment-owned events.db, whose `status` has different semantics.
        self._con.execute(
            "CREATE TABLE IF NOT EXISTS delay_event_candidates ("
            "candidate_id VARCHAR PRIMARY KEY, corpus VARCHAR, "
            "project_id VARCHAR, topic VARCHAR, event_date VARCHAR, "
            "actor VARCHAR, issue VARCHAR, quote VARCHAR, file_name VARCHAR, "
            "doc_id VARCHAR, page_number INTEGER, support_level VARCHAR, "
            "status VARCHAR, merged_into VARCHAR, created_at VARCHAR, "
            "decided_at VARCHAR, decided_by VARCHAR, reason VARCHAR)"
        )
        # Defensive backfill: older DBs predate the `reason` column.
        try:
            self._con.execute("ALTER TABLE delay_event_candidates "
                              "ADD COLUMN IF NOT EXISTS reason VARCHAR")
        except Exception:
            pass
        logger.info("[MemoryStore] Ready")

    @property
    def con(self):
        return self._con

    @property
    def lock(self):
        return self._db_lock


_instance: Optional[MemoryStore] = None


def get_memory_store() -> MemoryStore:
    global _instance
    if _instance is None:
        _instance = MemoryStore()
    return _instance
