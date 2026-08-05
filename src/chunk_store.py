"""
Chunk store — persistent local mirror of RAG chunk text for lexical retrieval.

The vector store (Pinecone/Qdrant) holds chunk embeddings, but its chunk TEXT is
not repopulated into memory after a restart. To run a lexical (BM25/keyword)
retrieval lane alongside dense vectors, we mirror every chunk's text to a local
DuckDB file at ingest time and sync it to GCS (Cloud Run is stateless).

Schema: chunks(chunk_id, doc_id, file_name, page_number, text)
The lexical_index module builds a DuckDB FTS index over this table.
"""
import hashlib
import threading
from pathlib import Path
from typing import Dict, List, Optional

import duckdb

from .config import STORAGE_DIR
from .logger import logger

CHUNKS_DIR = STORAGE_DIR / "chunks"
CHUNKS_DB = CHUNKS_DIR / "chunks.db"


def _chunk_id(file_name: str, page_number: int, text: str, project_id: str = "") -> str:
    """Stable id for a chunk (dedupe across re-ingests of the same content)."""
    h = hashlib.sha256(
        f"{project_id}|{file_name}|{page_number}|{text}".encode("utf-8")
    ).hexdigest()
    return h[:24]


class ChunkStore:
    """Singleton DuckDB-backed store of chunk text for lexical search."""

    _instance: Optional["ChunkStore"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._db_lock = threading.RLock()
                    inst._con = None
                    inst._dirty = True  # FTS index needs (re)build
                    inst._init_db()
                    cls._instance = inst
        return cls._instance

    # ── Setup ────────────────────────────────────────────────
    def _init_db(self):
        CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
        # Pull the latest DB from GCS first (stateless Cloud Run).
        try:
            from .gcs_storage import sync_chunks_from_gcs
            sync_chunks_from_gcs()
        except Exception:
            pass
        try:
            self._con = duckdb.connect(str(CHUNKS_DB))
            self._con.execute(
                "CREATE TABLE IF NOT EXISTS chunks ("
                "chunk_id VARCHAR PRIMARY KEY, doc_id VARCHAR, "
                "file_name VARCHAR, page_number INTEGER, text VARCHAR, project_id VARCHAR DEFAULT '')"
            )
            self._ensure_document_index_schema()
            cols = {r[1] for r in self._con.execute("PRAGMA table_info('chunks')").fetchall()}
            if "project_id" not in cols:
                self._con.execute("ALTER TABLE chunks ADD COLUMN project_id VARCHAR DEFAULT ''")
            logger.info(f"[ChunkStore] Ready ({self.count()} chunks)")
        except Exception as e:
            logger.error(f"[ChunkStore] init failed: {e}")
            # In-memory fallback so the app still runs (lexical lane degrades).
            self._con = duckdb.connect(":memory:")
            self._con.execute(
                "CREATE TABLE IF NOT EXISTS chunks ("
                "chunk_id VARCHAR PRIMARY KEY, doc_id VARCHAR, "
                "file_name VARCHAR, page_number INTEGER, text VARCHAR, project_id VARCHAR DEFAULT '')"
            )
            self._ensure_document_index_schema()

    def _ensure_document_index_schema(self) -> None:
        """Create the durable document-level retrieval tier.

        It deliberately lives in the same DuckDB file as the page chunks so its
        GCS checkpoint and tenant boundary cannot drift away from the evidence it
        describes.
        """
        self._con.execute(
            "CREATE TABLE IF NOT EXISTS document_index ("
            "search_id VARCHAR PRIMARY KEY, project_id VARCHAR NOT NULL, "
            "doc_id VARCHAR NOT NULL, file_name VARCHAR NOT NULL, reference VARCHAR, "
            "title VARCHAR, description VARCHAR, document_family VARCHAR, "
            "parties_json VARCHAR, topics_json VARCHAR, sheet_names_json VARCHAR, "
            "metadata_date VARCHAR, metadata_date_source VARCHAR, ocr_quality VARCHAR, "
            "content_hash VARCHAR, search_text VARCHAR, updated_at VARCHAR)"
        )
        self._con.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_document_index_project_doc "
            "ON document_index(project_id, doc_id)"
        )

    def connection(self):
        return self._con

    # ── Writes ───────────────────────────────────────────────
    def add_chunks(self, rows: List[Dict]) -> int:
        """Insert chunk rows. Each row: {doc_id, file_name, page_number, text}.
        Returns number of new rows inserted (existing chunk_ids skipped)."""
        if not rows:
            return 0
        with self._db_lock:
            before = self.count()
            for r in rows:
                text = (r.get("text") or "").strip()
                if not text:
                    continue
                fname = r.get("file_name", "Unknown")
                try:
                    page = int(r.get("page_number", 1))
                except (TypeError, ValueError):
                    page = 1
                project_id = str(r.get("project_id") or "")
                if not project_id:
                    try:
                        from .project_context import get_current_project_id
                        project_id = get_current_project_id()
                    except Exception:
                        pass
                if not project_id:
                    raise ValueError("project_id is required for chunk storage")
                cid = _chunk_id(fname, page, text, project_id)
                try:
                    self._con.execute(
                        "INSERT OR IGNORE INTO chunks "
                        "(chunk_id,doc_id,file_name,page_number,text,project_id) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        [cid, r.get("doc_id", ""), fname, page, text, project_id],
                    )
                except Exception as e:
                    logger.debug(f"[ChunkStore] insert skipped: {e}")
            inserted = self.count() - before
            if inserted:
                self._dirty = True
                self._persist()
        logger.info(f"[ChunkStore] +{inserted} chunks ({self.count()} total)")
        return inserted

    def delete_by_file(self, file_name: str, project_id: str = "") -> int:
        project_id = (project_id or "").strip()
        if not project_id:
            raise ValueError("project_id is required for chunk deletion")
        with self._db_lock:
            try:
                before = self.count()
                indexed_before = int(self._con.execute(
                    "SELECT COUNT(*) FROM document_index WHERE file_name=? AND project_id=?",
                    [file_name, project_id],
                ).fetchone()[0])
                self._con.execute(
                    "DELETE FROM chunks WHERE file_name = ? AND project_id = ?",
                    [file_name, project_id],
                )
                self._con.execute(
                    "DELETE FROM document_index WHERE file_name = ? AND project_id = ?",
                    [file_name, project_id],
                )
                removed = before - self.count()
                if removed or indexed_before:
                    self._dirty = True
                    self._persist()
                return removed
            except Exception as e:
                logger.warning(f"[ChunkStore] delete failed: {e}")
                return 0

    def _persist(self):
        """Checkpoint DuckDB and sync to GCS."""
        try:
            self._con.execute("CHECKPOINT")
        except Exception:
            pass
        try:
            from .gcs_storage import sync_chunks_to_gcs
            sync_chunks_to_gcs()
        except Exception:
            pass

    # ── Reads ────────────────────────────────────────────────
    def count(self) -> int:
        try:
            return int(self._con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        except Exception:
            return 0

    def is_empty(self) -> bool:
        return self.count() == 0

    def mark_clean(self):
        self._dirty = False

    def is_dirty(self) -> bool:
        return self._dirty


def get_chunk_store() -> ChunkStore:
    """Get the singleton ChunkStore."""
    return ChunkStore()
