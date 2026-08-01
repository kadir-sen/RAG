"""
Lexical retrieval lane — keyword/BM25 signals that complement dense vectors.

Two signals, both living OUTSIDE the vector DB (the user's "vektör DB dışı
ilişkili kelimeler" idea):

  1. Chunk-level BM25 over the chunk store (DuckDB FTS). Catches exact terms,
     codes, and names that dense embeddings miss. Falls back to LIKE if the FTS
     extension can't load.
  2. Document-level keyword match over persisted metadata: notice subject/topics/
     actions (light_graph), registry llm_topics/llm_summary, catalog semantic_tags.
     Returns a per-doc_id boost used to lift chunks whose parent doc is on-topic.

Both are fused with the dense lane via Reciprocal Rank Fusion in document_rag.
"""
import threading
from typing import Dict, List, Optional

from .logger import logger


class LexicalIndex:
    """Singleton lexical search over chunk text + document metadata."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._fts_lock = threading.RLock()
                    inst._fts_ready = False
                    inst._fts_available = None  # unknown until first attempt
                    cls._instance = inst
        return cls._instance

    # ── Chunk-level BM25 ─────────────────────────────────────
    def _ensure_fts(self) -> bool:
        """(Re)build the DuckDB FTS index over chunks if stale. Returns availability."""
        from .chunk_store import get_chunk_store
        cs = get_chunk_store()
        if cs.is_empty():
            return False
        with self._fts_lock:
            if self._fts_ready and not cs.is_dirty():
                return True
            con = cs.connection()
            try:
                con.execute("INSTALL fts; LOAD fts;")
                con.execute(
                    "PRAGMA create_fts_index('chunks', 'chunk_id', 'text', overwrite=1)"
                )
                self._fts_ready = True
                self._fts_available = True
                cs.mark_clean()
                logger.info("[Lexical] FTS index built over chunks")
                return True
            except Exception as e:
                self._fts_available = False
                logger.warning(f"[Lexical] FTS unavailable, using LIKE fallback: {e}")
                return False

    def search_chunks(self, query: str, top_k: int = 30,
                      project_id: Optional[str] = None) -> List[Dict]:
        """Return chunk candidates ranked by BM25 (or LIKE fallback).

        Each item: {chunk_id, doc_id, file_name, page_number, text, lex_score}.
        """
        project_id = (project_id or "").strip()
        if not project_id:
            raise ValueError("project_id is required for lexical search")
        query = (query or "").strip()
        if not query:
            return []
        from .chunk_store import get_chunk_store
        cs = get_chunk_store()
        if cs.is_empty():
            return []
        con = cs.connection()

        if self._ensure_fts():
            try:
                where = "score IS NOT NULL"
                params = [query]
                where += " AND project_id = ?"
                params.append(project_id)
                params.append(top_k)
                rows = con.execute(
                    "SELECT chunk_id, doc_id, file_name, page_number, text, "
                    "fts_main_chunks.match_bm25(chunk_id, ?) AS score "
                    f"FROM chunks WHERE {where} ORDER BY score DESC LIMIT ?",
                    params,
                ).fetchall()
                return [
                    {"chunk_id": r[0], "doc_id": r[1], "file_name": r[2],
                     "page_number": r[3], "text": r[4], "lex_score": float(r[5] or 0.0)}
                    for r in rows
                ]
            except Exception as e:
                logger.warning(f"[Lexical] BM25 query failed, LIKE fallback: {e}")

        # LIKE fallback: score = number of distinct query tokens present
        tokens = [t for t in _tokenize(query) if len(t) >= 3][:8]
        if not tokens:
            return []
        try:
            score_expr = " + ".join(
                ["(CASE WHEN LOWER(text) LIKE ? THEN 1 ELSE 0 END)" for _ in tokens]
            )
            params = [f"%{t}%" for t in tokens]
            project_clause = " AND project_id = ?"
            sql = (
                f"SELECT chunk_id, doc_id, file_name, page_number, text, ({score_expr}) AS score "
                f"FROM chunks WHERE {score_expr} > 0{project_clause} ORDER BY score DESC LIMIT ?"
            )
            tail = [project_id, top_k]
            rows = con.execute(sql, params + params + tail).fetchall()
            return [
                {"chunk_id": r[0], "doc_id": r[1], "file_name": r[2],
                 "page_number": r[3], "text": r[4], "lex_score": float(r[5] or 0.0)}
                for r in rows
            ]
        except Exception as e:
            logger.warning(f"[Lexical] LIKE fallback failed: {e}")
            return []

    # ── Document-level keyword signal ────────────────────────
    def match_docs(self, terms: List[str], limit: int = 25,
                   project_id: Optional[str] = None) -> Dict[str, float]:
        """Return {doc_id: boost} from persisted document metadata.

        Aggregates three keyword sources, normalized to a 0..1 boost per doc_id.
        """
        project_id = (project_id or "").strip()
        if not project_id:
            raise ValueError("project_id is required for lexical document matching")
        terms = [t for t in (terms or []) if t and len(t) >= 2]
        if not terms:
            return {}
        scores: Dict[str, float] = {}

        # 1. Notice subject/topics/actions (light_graph)
        try:
            from .light_graph import get_light_graph
            for node in get_light_graph().search_broad(terms, limit=limit):
                if (node.get("project_id") or "") != project_id:
                    continue
                did = node.get("doc_id")
                if did:
                    scores[did] = scores.get(did, 0.0) + float(node.get("relevance_score", 1))
        except Exception as e:
            logger.debug(f"[Lexical] notice match skipped: {e}")

        # 2. Registry llm_topics + llm_summary
        try:
            from .document_registry import get_document_registry
            tl = [t.lower() for t in terms]
            for rec in get_document_registry().get_completed(project_id=project_id):
                blob = " ".join(
                    [(rec.llm_summary or "")] + list(getattr(rec, "llm_topics", None) or [])
                ).lower()
                if not blob:
                    continue
                hits = sum(1 for t in tl if t in blob)
                if hits:
                    scores[rec.doc_id] = scores.get(rec.doc_id, 0.0) + hits
        except Exception as e:
            logger.debug(f"[Lexical] registry match skipped: {e}")

        if not scores:
            return {}
        # Normalize to 0..1
        mx = max(scores.values())
        if mx > 0:
            scores = {k: v / mx for k, v in scores.items()}
        return scores


def rrf_fuse(dense: List[Dict], lexical: List[Dict],
             doc_boost: Dict[str, float], rrf_k: int = 60) -> List[Dict]:
    """Reciprocal Rank Fusion of two ranked candidate lists + doc-keyword boost.

    Pure function (no vector-store / llama_index dependency) so it is unit-testable
    in isolation. Each candidate must carry a stable 'key'. Returns node dicts
    sorted by fused score (descending), richer metadata merged across lanes.
    """
    pool: Dict[str, Dict] = {}

    def _absorb(lst: List[Dict]):
        for rank, nd in enumerate(lst):
            key = nd.get("key")
            if not key:
                continue
            if key not in pool:
                pool[key] = dict(nd)
                pool[key]["rrf"] = 0.0
            else:
                for f in ("file_path", "total_pages", "doc_id", "text"):
                    if not pool[key].get(f) and nd.get(f):
                        pool[key][f] = nd[f]
            pool[key]["rrf"] += 1.0 / (rrf_k + rank + 1)

    _absorb(dense)
    _absorb(lexical)

    # Document-keyword boost as a gentle tiebreaker: scaled to at most HALF of a
    # single top-rank RRF contribution so it nudges ties without overriding the
    # actual dense/lexical rank fusion.
    boost_unit = 0.5 / (rrf_k + 1)
    for nd in pool.values():
        b = doc_boost.get(nd.get("doc_id"), 0.0)
        if b:
            nd["rrf"] += boost_unit * b

    return sorted(pool.values(), key=lambda x: x.get("rrf", 0.0), reverse=True)


def _tokenize(text: str) -> List[str]:
    import re
    return [t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if t]


def get_lexical_index() -> LexicalIndex:
    """Get the singleton LexicalIndex."""
    return LexicalIndex()
