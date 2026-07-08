"""Named Entity Registry — corpus-scoped canonical entities for Trust Guard.

Built at INGEST time (file_router hook, LLM-free: notice sender/recipient/cc,
subject proper-nouns, filenames) and by the backfill script
(scripts/build_entity_registry.py — chunk-text proper-noun extraction for
corpora without notices, e.g. edinburgh). Trust Guard's check_entities reads
this registry first — a fast deterministic lookup instead of runtime DuckDB FTS
(which rebuilds the full-text index after every ingest).

DuckDB-backed singleton at storage/entities/entities.db, mirroring the
interaction_log pattern. Separate file from interactions.db: corpus data vs
telemetry, and backfill bulk writes shouldn't contend with per-query telemetry.
No GCS sync — the registry is fully rebuildable from the backfill script.

Schema:
  entities(entity_id PK, canonical_name, canonical_lower, entity_type,
           corpus, aliases JSON, doc_count, source_docs JSON,
           first_seen, last_seen, confidence)
"""
from __future__ import annotations

import hashlib
import json
import threading
from typing import Dict, List, Optional

import duckdb

from .config import STORAGE_DIR
from .logger import logger

ENTITIES_DIR = STORAGE_DIR / "entities"
ENTITIES_DB = ENTITIES_DIR / "entities.db"

_SOURCE_DOCS_CAP = 20
ENTITY_TYPES = ("person", "org", "document", "other")


def _entity_id(corpus: str, canonical_lower: str) -> str:
    return hashlib.sha256(f"{corpus}|{canonical_lower}".encode("utf-8")).hexdigest()[:24]


class EntityRegistry:
    """Singleton DuckDB store of corpus-scoped named entities."""

    _instance: Optional["EntityRegistry"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._db_lock = threading.RLock()
                    inst._con = None
                    # Per-corpus cache of (canonical_name, aliases) for fuzzy
                    # `similar()` lookups; invalidated on upsert.
                    inst._name_cache = {}
                    inst._init_db()
                    cls._instance = inst
        return cls._instance

    def _init_db(self):
        ENTITIES_DIR.mkdir(parents=True, exist_ok=True)
        try:
            self._con = duckdb.connect(str(ENTITIES_DB))
        except Exception as e:
            logger.error(f"[EntityRegistry] init failed ({e}); in-memory fallback")
            self._con = duckdb.connect(":memory:")
        self._con.execute(
            "CREATE TABLE IF NOT EXISTS entities ("
            "entity_id VARCHAR PRIMARY KEY, canonical_name VARCHAR, "
            "canonical_lower VARCHAR, entity_type VARCHAR, corpus VARCHAR, "
            "aliases VARCHAR, doc_count INTEGER, source_docs VARCHAR, "
            "first_seen VARCHAR, last_seen VARCHAR, confidence DOUBLE)"
        )
        self._con.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_corpus_name "
            "ON entities (corpus, canonical_lower)"
        )
        logger.info(f"[EntityRegistry] Ready ({self.total()} entities)")

    # ── Writes ────────────────────────────────────────────────

    def upsert(self, name: str, entity_type: str = "other", corpus: str = "demo",
               doc_id: str = "", aliases: Optional[List[str]] = None,
               confidence: float = 0.5, ts: str = "") -> None:
        """Insert or merge one entity observation. Best-effort, never raises.

        Merging: doc_count += 1 per NEW doc_id, aliases unioned, confidence
        keeps the max, last_seen updated.
        """
        canonical = " ".join((name or "").split()).strip()
        if len(canonical) < 3:
            return
        corpus = (corpus or "demo").lower()
        low = canonical.lower()
        eid = _entity_id(corpus, low)
        new_aliases = sorted({a.strip() for a in (aliases or []) if a and a.strip()})
        try:
            with self._db_lock:
                row = self._con.execute(
                    "SELECT aliases, doc_count, source_docs, confidence "
                    "FROM entities WHERE entity_id = ?", [eid],
                ).fetchone()
                if row is None:
                    self._con.execute(
                        "INSERT OR IGNORE INTO entities VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        [eid, canonical, low,
                         entity_type if entity_type in ENTITY_TYPES else "other",
                         corpus, json.dumps(new_aliases, ensure_ascii=False),
                         1 if doc_id else 0,
                         json.dumps([doc_id] if doc_id else [], ensure_ascii=False),
                         ts, ts, float(confidence)],
                    )
                else:
                    cur_aliases = set(json.loads(row[0] or "[]"))
                    cur_docs = json.loads(row[2] or "[]")
                    doc_count = int(row[1] or 0)
                    if doc_id and doc_id not in cur_docs:
                        doc_count += 1
                        if len(cur_docs) < _SOURCE_DOCS_CAP:
                            cur_docs.append(doc_id)
                    cur_aliases.update(new_aliases)
                    self._con.execute(
                        "UPDATE entities SET aliases = ?, doc_count = ?, "
                        "source_docs = ?, last_seen = ?, confidence = ? "
                        "WHERE entity_id = ?",
                        [json.dumps(sorted(cur_aliases), ensure_ascii=False),
                         doc_count, json.dumps(cur_docs, ensure_ascii=False),
                         ts, max(float(confidence), float(row[3] or 0.0)), eid],
                    )
                self._name_cache.pop(corpus, None)
                self._name_cache.pop(f"{corpus}::counts", None)
        except Exception as e:
            logger.debug(f"[EntityRegistry] upsert skipped ({name}): {e}")

    def add_alias(self, canonical_name: str, alias: str, corpus: str = "demo") -> None:
        """Attach an alias to an existing canonical entity."""
        self.upsert(canonical_name, corpus=corpus, aliases=[alias])

    def bulk_upsert(self, name: str, entity_type: str = "other", corpus: str = "demo",
                    doc_ids: Optional[List[str]] = None,
                    aliases: Optional[List[str]] = None,
                    confidence: float = 0.5, ts: str = "") -> None:
        """One write per entity with the full doc set — the backfill fast path.

        Unlike upsert (one observation), doc_count is set to the number of
        distinct doc_ids provided (merged with any existing docs)."""
        canonical = " ".join((name or "").split()).strip()
        if len(canonical) < 3:
            return
        corpus = (corpus or "demo").lower()
        low = canonical.lower()
        eid = _entity_id(corpus, low)
        ids = sorted({d for d in (doc_ids or []) if d})
        new_aliases = sorted({a.strip() for a in (aliases or []) if a and a.strip()})
        try:
            with self._db_lock:
                row = self._con.execute(
                    "SELECT aliases, doc_count, source_docs, confidence "
                    "FROM entities WHERE entity_id = ?", [eid],
                ).fetchone()
                if row is None:
                    self._con.execute(
                        "INSERT OR IGNORE INTO entities VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        [eid, canonical, low,
                         entity_type if entity_type in ENTITY_TYPES else "other",
                         corpus, json.dumps(new_aliases, ensure_ascii=False),
                         len(ids),
                         json.dumps(ids[:_SOURCE_DOCS_CAP], ensure_ascii=False),
                         ts, ts, float(confidence)],
                    )
                else:
                    cur_docs = set(json.loads(row[2] or "[]"))
                    merged_docs = sorted(cur_docs | set(ids))
                    cur_aliases = set(json.loads(row[0] or "[]"))
                    cur_aliases.update(new_aliases)
                    self._con.execute(
                        "UPDATE entities SET aliases = ?, doc_count = ?, "
                        "source_docs = ?, last_seen = ?, confidence = ? "
                        "WHERE entity_id = ?",
                        [json.dumps(sorted(cur_aliases), ensure_ascii=False),
                         max(int(row[1] or 0), len(merged_docs)),
                         json.dumps(merged_docs[:_SOURCE_DOCS_CAP], ensure_ascii=False),
                         ts, max(float(confidence), float(row[3] or 0.0)), eid],
                    )
                self._name_cache.pop(corpus, None)
                self._name_cache.pop(f"{corpus}::counts", None)
        except Exception as e:
            logger.debug(f"[EntityRegistry] bulk_upsert skipped ({name}): {e}")

    # ── Reads ─────────────────────────────────────────────────

    def find(self, name: str, corpus: str = "demo") -> Optional[Dict]:
        """Exact case-insensitive match on canonical name OR alias."""
        low = " ".join((name or "").split()).strip().lower()
        if not low:
            return None
        corpus = (corpus or "demo").lower()
        try:
            with self._db_lock:
                row = self._con.execute(
                    "SELECT canonical_name, entity_type, aliases, doc_count, confidence "
                    "FROM entities WHERE corpus = ? AND canonical_lower = ?",
                    [corpus, low],
                ).fetchone()
                if row is None:
                    # Alias scan (aliases are JSON arrays; list is small per corpus)
                    for r in self._con.execute(
                        "SELECT canonical_name, entity_type, aliases, doc_count, confidence "
                        "FROM entities WHERE corpus = ? AND aliases != '[]'", [corpus],
                    ).fetchall():
                        if low in (a.lower() for a in json.loads(r[2] or "[]")):
                            row = r
                            break
            if row is None:
                return None
            return {"canonical_name": row[0], "entity_type": row[1],
                    "aliases": json.loads(row[2] or "[]"),
                    "doc_count": int(row[3] or 0), "confidence": float(row[4] or 0.0)}
        except Exception as e:
            logger.debug(f"[EntityRegistry] find failed ({name}): {e}")
            return None

    def similar(self, name: str, corpus: str = "demo", cutoff: int = 80,
                limit: int = 3) -> List[str]:
        """Fuzzy 'did you mean' candidates from the corpus's canonical names.

        Two-stage: token_set_ratio prefilter (catches shared surnames like
        "MacDonald"), then re-rank by mean(token_set, full-string ratio) plus
        a doc_count prominence boost — character distance alone cannot pick
        "Mott MacDonald" (20 docs) over "Morna McDonald" (2 docs) for the
        query "Morrison MacDonald", but a misspelling almost always intends
        the prominent entity, not the obscure one."""
        import math
        low = " ".join((name or "").split()).strip().lower()
        if not low:
            return []
        try:
            from rapidfuzz import fuzz, process
        except ImportError:
            return []
        names = self._corpus_names(corpus)
        if not names:
            return []
        try:
            prelim = process.extract(
                low, list(names.keys()), scorer=fuzz.token_set_ratio,
                limit=max(limit * 5, 15), score_cutoff=cutoff,
            )
            counts = self._corpus_doc_counts(corpus)
            reranked = sorted(
                ((key,
                  (score + fuzz.ratio(low, key)) / 2.0
                  + 6.0 * math.log10(1 + counts.get(key, 0)))
                 for key, score, _ in prelim),
                key=lambda kv: -kv[1],
            )
        except Exception:
            return []
        return [names[k] for k, _ in reranked[:limit] if names[k].lower() != low]

    def _corpus_doc_counts(self, corpus: str) -> Dict[str, int]:
        """{canonical_lower: doc_count} for one corpus (piggybacks name cache TTL)."""
        corpus = (corpus or "demo").lower()
        cached = self._name_cache.get(f"{corpus}::counts")
        if cached is not None:
            return cached
        try:
            with self._db_lock:
                rows = self._con.execute(
                    "SELECT canonical_lower, doc_count FROM entities WHERE corpus = ?",
                    [corpus],
                ).fetchall()
            counts = {r[0]: int(r[1] or 0) for r in rows}
        except Exception:
            counts = {}
        self._name_cache[f"{corpus}::counts"] = counts
        return counts

    def _corpus_names(self, corpus: str) -> Dict[str, str]:
        """{canonical_lower: canonical_name} for one corpus, cached in memory."""
        corpus = (corpus or "demo").lower()
        cached = self._name_cache.get(corpus)
        if cached is not None:
            return cached
        try:
            with self._db_lock:
                rows = self._con.execute(
                    "SELECT canonical_lower, canonical_name FROM entities "
                    "WHERE corpus = ?", [corpus],
                ).fetchall()
            names = {r[0]: r[1] for r in rows}
        except Exception as e:
            logger.debug(f"[EntityRegistry] name cache load failed: {e}")
            names = {}
        self._name_cache[corpus] = names
        return names

    def count(self, corpus: str = "demo") -> int:
        try:
            with self._db_lock:
                return int(self._con.execute(
                    "SELECT COUNT(*) FROM entities WHERE corpus = ?",
                    [(corpus or "demo").lower()],
                ).fetchone()[0])
        except Exception:
            return 0

    def total(self) -> int:
        try:
            return int(self._con.execute("SELECT COUNT(*) FROM entities").fetchone()[0])
        except Exception:
            return 0

    # ── Ingest helper ─────────────────────────────────────────

    def ingest_from_notice(self, doc_id: str, file_name: str,
                           notice_summary: Optional[Dict], corpus: str = "demo",
                           ts: str = "") -> None:
        """Seed entities from an ingest-time notice summary (LLM-free).

        sender/recipient/cc → person-or-org (conf 0.8); subject proper-nouns
        (conf 0.6); the filename itself as a document entity.
        """
        try:
            summary = notice_summary or {}
            for key, conf in (("sender", 0.8), ("recipient", 0.8)):
                val = (summary.get(key) or "").strip()
                if val:
                    self.upsert(val, "org", corpus, doc_id, confidence=conf, ts=ts)
            for cc in summary.get("cc_list") or []:
                if cc and cc.strip():
                    self.upsert(cc.strip(), "org", corpus, doc_id, confidence=0.7, ts=ts)
            subject = (summary.get("subject") or "").strip()
            if subject:
                from .trust_guard import _extract_proper_nouns
                for noun in _extract_proper_nouns(subject):
                    self.upsert(noun, "other", corpus, doc_id, confidence=0.6, ts=ts)
            if file_name:
                self.upsert(file_name, "document", corpus, doc_id, confidence=0.9, ts=ts)
        except Exception as e:
            logger.debug(f"[EntityRegistry] notice ingest skipped ({file_name}): {e}")


_instance: Optional[EntityRegistry] = None


def get_entity_registry() -> EntityRegistry:
    global _instance
    if _instance is None:
        _instance = EntityRegistry()
    return _instance
