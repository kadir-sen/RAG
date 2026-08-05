"""
Document topic clustering — groups documents in the library by semantic
similarity using chunk embeddings already stored in Pinecone.

Pipeline:
  1. fetch_doc_centroid(doc_id) — pull chunk vectors via Pinecone, mean-pool
     and L2-normalize into a single document-level centroid.
  2. cluster_all() — run HDBSCAN (fallback: AgglomerativeClustering) over all
     centroids; produce cluster_id -> [doc_id] groups.
  3. label_clusters() — for each cluster, ask the LLM to generate a 2-4 word
     human-readable label using top filenames + notice subjects as context.
  4. assign_new_doc(doc_id) — for new ingests, cosine to existing cluster
     centroids; ≥ ASSIGN_THRESHOLD → assign; otherwise mark "uncategorized"
     and queue for next re-cluster.

State is persisted atomically to storage/document_clusters.json.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from .config import STORAGE_DIR
from .logger import logger


CLUSTERS_FILE = STORAGE_DIR / "document_clusters.json"

# Cosine similarity threshold for online assignment to an existing cluster.
ASSIGN_THRESHOLD = 0.55

# Below this many docs, clustering is skipped — everything stays uncategorized.
MIN_DOCS_FOR_CLUSTERING = 5

# HDBSCAN params
HDBSCAN_MIN_CLUSTER_SIZE = 3
HDBSCAN_MIN_SAMPLES = 2

# Agglomerative fallback distance threshold (cosine distance after L2-norm).
AGGLO_DISTANCE_THRESHOLD = 0.45

UNCATEGORIZED_ID = "uncategorized"
UNCATEGORIZED_LABEL = "Other"

# Per-cluster relabel trigger — re-label once this many new docs have been
# assigned to a cluster since its last LLM-generated label.
RELABEL_AFTER_NEW_DOCS = 5


# ── Helpers ─────────────────────────────────────────────────────────


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec)
    if norm == 0:
        return vec
    return vec / norm


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    # Inputs assumed already L2-normalized; dot product = cosine.
    return float(np.dot(a, b))


# ── Persistence schema ──────────────────────────────────────────────


@dataclass
class ClusterEntry:
    cluster_id: str
    label: str
    centroid: List[float]
    doc_count: int = 0
    file_types: List[str] = field(default_factory=list)
    doc_count_since_relabel: int = 0


# ── Singleton clusterer ─────────────────────────────────────────────


class DocumentClusterer:
    _instance: Optional["DocumentClusterer"] = None
    _bootstrap_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._bootstrap_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._lock = threading.Lock()
                    inst._clusters: Dict[str, ClusterEntry] = {}
                    inst._assignments: Dict[str, str] = {}
                    inst._centroid_cache: Dict[str, np.ndarray] = {}
                    inst._computed_at: str = ""
                    inst._load()
                    cls._instance = inst
        return cls._instance

    # ── Persistence ────────────────────────────────────────────────

    def _load(self):
        if not CLUSTERS_FILE.exists():
            return
        try:
            data = json.loads(CLUSTERS_FILE.read_text(encoding="utf-8"))
            self._computed_at = data.get("computed_at", "")
            for cid, raw in (data.get("clusters") or {}).items():
                self._clusters[cid] = ClusterEntry(
                    cluster_id=cid,
                    label=raw.get("label", UNCATEGORIZED_LABEL),
                    centroid=list(raw.get("centroid") or []),
                    doc_count=int(raw.get("doc_count", 0)),
                    file_types=list(raw.get("file_types") or []),
                    doc_count_since_relabel=int(raw.get("doc_count_since_relabel", 0)),
                )
            self._assignments = dict(data.get("assignments") or {})
            logger.info(
                f"[Clusterer] Loaded {len(self._clusters)} clusters, "
                f"{len(self._assignments)} assignments"
            )
        except Exception as e:
            logger.error(f"[Clusterer] Load failed: {e}")

    def _persist_locked(self):
        """Atomic write. Must be called while holding self._lock."""
        CLUSTERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "computed_at": self._computed_at or datetime.utcnow().isoformat(),
            "clusters": {
                cid: {
                    "label": c.label,
                    "centroid": [float(x) for x in c.centroid],
                    "doc_count": c.doc_count,
                    "file_types": c.file_types,
                    "doc_count_since_relabel": c.doc_count_since_relabel,
                }
                for cid, c in self._clusters.items()
            },
            "assignments": self._assignments,
        }
        tmp = CLUSTERS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, CLUSTERS_FILE)

        # Mirror denormalized cluster info into DocumentRegistry for fast reads.
        try:
            from .document_registry import get_document_registry
            registry = get_document_registry()
            for doc_id, cluster_id in self._assignments.items():
                rec = registry.get(doc_id)
                if not rec:
                    continue
                label = self._clusters.get(cluster_id, ClusterEntry(
                    cluster_id=cluster_id, label=UNCATEGORIZED_LABEL, centroid=[])
                ).label
                rec.cluster_id = cluster_id
                rec.cluster_label = label
            registry._save()  # type: ignore[attr-defined]
        except Exception as e:
            logger.warning(f"[Clusterer] Registry mirror failed: {e}")

    # ── Public read API ────────────────────────────────────────────

    def get_assignment(self, doc_id: str) -> Tuple[Optional[str], Optional[str]]:
        cluster_id = self._assignments.get(doc_id)
        if not cluster_id:
            return None, None
        entry = self._clusters.get(cluster_id)
        return cluster_id, (entry.label if entry else None)

    def list_clusters(self) -> List[Dict]:
        out: List[Dict] = []
        for cid, c in self._clusters.items():
            out.append({
                "cluster_id": cid,
                "label": c.label,
                "doc_count": c.doc_count,
                "file_types": list(c.file_types),
            })
        # Sort: largest first, "Other" last
        out.sort(key=lambda x: (x["cluster_id"] == UNCATEGORIZED_ID, -x["doc_count"]))
        return out

    # ── Embedding access ───────────────────────────────────────────

    def fetch_doc_centroid(
        self,
        doc_id: str,
        max_chunks: int = 200,
        use_cache: bool = True,
    ) -> Optional[np.ndarray]:
        """Return an L2-normalized mean-pooled centroid for the document.

        Filters Pinecone on ``file_name`` rather than ``doc_id`` because
        LlamaIndex's Document class auto-generates a UUID4 doc_id at insert
        time and overrides the metadata field — the registry's deterministic
        16-hex doc_id never reaches Pinecone. ``file_name`` is preserved
        verbatim and is unique per registry record.
        """
        if use_cache and doc_id in self._centroid_cache:
            return self._centroid_cache[doc_id]

        # Resolve file_name from registry — that's our actual Pinecone handle.
        file_name: Optional[str] = None
        project_id = ""
        try:
            from .document_registry import get_document_registry
            rec = get_document_registry().get(doc_id)
            if rec is not None:
                file_name = rec.file_name
                project_id = (getattr(rec, "project_id", "") or "").strip()
        except Exception as e:
            logger.warning(f"[Clusterer] Registry lookup failed for {doc_id}: {e}")
        if not file_name or not project_id:
            return None

        try:
            from .document_rag import get_document_rag
            rag = get_document_rag()
        except Exception as e:
            logger.warning(f"[Clusterer] RAG not available: {e}")
            return None

        # Backend-agnostic: fetch raw chunk vectors for this file (Pinecone or Qdrant).
        raw = rag.fetch_doc_vectors(
            file_name, project_id=project_id, file_id=doc_id,
            max_chunks=max_chunks,
        )
        vectors: List[np.ndarray] = []
        for values in raw:
            if not values:
                continue
            vectors.append(_l2_normalize(np.asarray(values, dtype=np.float32)))

        if not vectors:
            return None

        mean = np.mean(np.stack(vectors, axis=0), axis=0)
        centroid = _l2_normalize(mean)
        if use_cache:
            self._centroid_cache[doc_id] = centroid
        return centroid

    # ── Clustering core ────────────────────────────────────────────

    def cluster_all(self, *, force: bool = False, project_id: str = "") -> Dict[str, List[str]]:
        """Re-cluster every completed document.

        Returns mapping cluster_id -> list of doc_ids.
        """
        from .document_registry import get_document_registry
        registry = get_document_registry()
        if project_id:
            from .project_context import set_current_project
            set_current_project(project_id)
        completed = registry.get_completed(project_id=project_id or None)
        doc_ids = [r.doc_id for r in completed]
        file_type_by_doc = {r.doc_id: r.file_type for r in completed}

        if len(doc_ids) < MIN_DOCS_FOR_CLUSTERING and not force:
            logger.info(
                f"[Clusterer] Skipping cluster_all: {len(doc_ids)} docs < "
                f"{MIN_DOCS_FOR_CLUSTERING}"
            )
            with self._lock:
                # Park everything in uncategorized.
                self._clusters = {}
                self._assignments = {d: UNCATEGORIZED_ID for d in doc_ids}
                if doc_ids:
                    self._clusters[UNCATEGORIZED_ID] = ClusterEntry(
                        cluster_id=UNCATEGORIZED_ID,
                        label=UNCATEGORIZED_LABEL,
                        centroid=[],
                        doc_count=len(doc_ids),
                        file_types=sorted({file_type_by_doc.get(d, "") for d in doc_ids if d}),
                    )
                self._computed_at = datetime.utcnow().isoformat()
                self._persist_locked()
            return {UNCATEGORIZED_ID: list(doc_ids)}

        # Pull centroids for every doc
        centroids: Dict[str, np.ndarray] = {}
        for did in doc_ids:
            c = self.fetch_doc_centroid(did)
            if c is not None:
                centroids[did] = c

        if len(centroids) < MIN_DOCS_FOR_CLUSTERING:
            logger.warning(
                f"[Clusterer] Only {len(centroids)} centroids available — "
                "skipping HDBSCAN, marking all uncategorized"
            )
            with self._lock:
                self._clusters = {}
                self._assignments = {d: UNCATEGORIZED_ID for d in doc_ids}
                if doc_ids:
                    self._clusters[UNCATEGORIZED_ID] = ClusterEntry(
                        cluster_id=UNCATEGORIZED_ID,
                        label=UNCATEGORIZED_LABEL,
                        centroid=[],
                        doc_count=len(doc_ids),
                        file_types=sorted({file_type_by_doc.get(d, "") for d in doc_ids if d}),
                    )
                self._computed_at = datetime.utcnow().isoformat()
                self._persist_locked()
            return {UNCATEGORIZED_ID: list(doc_ids)}

        ordered_ids = list(centroids.keys())
        X = np.stack([centroids[d] for d in ordered_ids], axis=0)
        labels = self._run_clustering(X)

        # Group doc_ids by raw label
        groups: Dict[int, List[str]] = {}
        for doc_id, lbl in zip(ordered_ids, labels):
            groups.setdefault(int(lbl), []).append(doc_id)

        # Build new cluster entries. Stable IDs: hash mapping from previous
        # centroids (so frontend "expanded" state survives re-cluster).
        new_clusters: Dict[str, ClusterEntry] = {}
        new_assignments: Dict[str, str] = {}
        old_centroid_pairs: List[Tuple[str, np.ndarray]] = [
            (cid, np.asarray(c.centroid, dtype=np.float32))
            for cid, c in self._clusters.items()
            if c.cluster_id != UNCATEGORIZED_ID and c.centroid
        ]
        used_old_ids: set = set()

        # Docs not in centroids (no embeddings) → uncategorized.
        missing_doc_ids = [d for d in doc_ids if d not in centroids]

        for raw_lbl, members in groups.items():
            if raw_lbl == -1:
                # HDBSCAN noise → uncategorized
                for d in members:
                    new_assignments[d] = UNCATEGORIZED_ID
                continue

            member_vecs = np.stack([centroids[d] for d in members], axis=0)
            cluster_centroid = _l2_normalize(np.mean(member_vecs, axis=0))

            # Stability: prefer reusing an existing cluster_id whose centroid
            # is closest to this new one.
            best_old_id: Optional[str] = None
            best_sim = -1.0
            for old_id, old_c in old_centroid_pairs:
                if old_id in used_old_ids or old_c.size == 0:
                    continue
                sim = _cosine(_l2_normalize(old_c), cluster_centroid)
                if sim > best_sim:
                    best_sim = sim
                    best_old_id = old_id
            if best_old_id is not None and best_sim >= 0.6:
                cluster_id = best_old_id
                used_old_ids.add(best_old_id)
            else:
                cluster_id = f"c_{uuid.uuid4().hex[:8]}"

            file_types = sorted({file_type_by_doc.get(d, "") for d in members if d})
            entry = ClusterEntry(
                cluster_id=cluster_id,
                label=UNCATEGORIZED_LABEL,  # placeholder, set in label_clusters
                centroid=cluster_centroid.tolist(),
                doc_count=len(members),
                file_types=[ft for ft in file_types if ft],
                doc_count_since_relabel=0,
            )
            # Carry over old label if we matched an existing cluster.
            old_entry = self._clusters.get(cluster_id)
            if old_entry and old_entry.label and old_entry.label != UNCATEGORIZED_LABEL:
                entry.label = old_entry.label
            new_clusters[cluster_id] = entry
            for d in members:
                new_assignments[d] = cluster_id

        for d in missing_doc_ids:
            new_assignments[d] = UNCATEGORIZED_ID

        # Build uncategorized entry if anything fell into it.
        uncats = [d for d, cid in new_assignments.items() if cid == UNCATEGORIZED_ID]
        if uncats:
            new_clusters[UNCATEGORIZED_ID] = ClusterEntry(
                cluster_id=UNCATEGORIZED_ID,
                label=UNCATEGORIZED_LABEL,
                centroid=[],
                doc_count=len(uncats),
                file_types=sorted({file_type_by_doc.get(d, "") for d in uncats if d}),
            )

        # Generate labels for clusters that don't have one.
        self._label_clusters_inplace(new_clusters, new_assignments)

        with self._lock:
            self._clusters = new_clusters
            self._assignments = new_assignments
            self._computed_at = datetime.utcnow().isoformat()
            self._persist_locked()

        result: Dict[str, List[str]] = {}
        for d, cid in new_assignments.items():
            result.setdefault(cid, []).append(d)
        logger.info(
            f"[Clusterer] Re-cluster done: {len(new_clusters)} clusters, "
            f"{len(new_assignments)} docs"
        )
        return result

    def _run_clustering(self, X: np.ndarray) -> np.ndarray:
        """Return integer cluster labels for the row vectors in X."""
        # Primary: HDBSCAN on L2-normalized vectors (euclidean ≈ √(2-2·cos)).
        try:
            import hdbscan  # type: ignore
            clusterer = hdbscan.HDBSCAN(
                min_cluster_size=HDBSCAN_MIN_CLUSTER_SIZE,
                min_samples=HDBSCAN_MIN_SAMPLES,
                metric="euclidean",
            )
            return clusterer.fit_predict(X)
        except Exception as e:
            logger.warning(f"[Clusterer] HDBSCAN unavailable ({e}), trying sklearn")

        # Fallback: AgglomerativeClustering with cosine distance.
        try:
            from sklearn.cluster import AgglomerativeClustering
            clusterer = AgglomerativeClustering(
                n_clusters=None,
                metric="cosine",
                linkage="average",
                distance_threshold=AGGLO_DISTANCE_THRESHOLD,
            )
            return clusterer.fit_predict(X)
        except Exception as e:
            logger.error(f"[Clusterer] All clustering backends failed: {e}")
            # Last resort: everything in one cluster
            return np.zeros(X.shape[0], dtype=int)

    # ── Labels ─────────────────────────────────────────────────────

    def _label_clusters_inplace(
        self,
        clusters: Dict[str, ClusterEntry],
        assignments: Dict[str, str],
    ):
        """Call LLM once per non-Other cluster that lacks a label."""
        try:
            from .document_registry import get_document_registry
            registry = get_document_registry()
        except Exception:
            registry = None

        # Build doc-by-cluster index for prompt context.
        cluster_to_docs: Dict[str, List[str]] = {}
        for doc_id, cid in assignments.items():
            cluster_to_docs.setdefault(cid, []).append(doc_id)

        for cid, entry in clusters.items():
            if cid == UNCATEGORIZED_ID:
                continue
            if entry.label and entry.label != UNCATEGORIZED_LABEL:
                continue
            members = cluster_to_docs.get(cid, [])[:3]
            label = self._generate_label(members, registry)
            entry.label = label or UNCATEGORIZED_LABEL
            entry.doc_count_since_relabel = 0

    def _generate_label(self, doc_ids: List[str], registry) -> str:
        """LLM call (cached) → 2-4 word topic label."""
        if not doc_ids:
            return UNCATEGORIZED_LABEL

        snippets: List[str] = []
        for did in doc_ids:
            rec = registry.get(did) if registry else None
            file_name = rec.file_name if rec else did
            subject = ""
            if rec and rec.notice_extracted:
                try:
                    from .notice_extractor import get_notice_extractor
                    notice = get_notice_extractor().load_notice(did)
                    if notice:
                        subject = (notice.subject or "") + " "
                        topics = " ".join(notice.key_topics or []) if hasattr(notice, "key_topics") else ""
                        if topics:
                            subject += topics
                except Exception:
                    pass
            snippets.append(f"- {file_name}: {subject.strip()[:120]}")

        prompt = (
            "You will see 1-3 document filenames with optional subjects. "
            "Generate a short topic label (2-4 words, Title Case, no punctuation) "
            "that describes the common theme. Reply with ONLY the label.\n\n"
            "Documents:\n" + "\n".join(snippets)
        )

        try:
            from .llm_client import generate_text
            resp = generate_text(
                prompt,
                system="You generate concise document topic labels for construction project libraries.",
                max_tokens=20,
                provider="gemini",
                task_type="ingestion_cluster_label",
            )
            text = (resp.text or "").strip().strip('"').strip("'")
            # First line only, trim trailing punctuation
            text = text.splitlines()[0].strip().rstrip(".,:;")
            if not text:
                return UNCATEGORIZED_LABEL
            # Cap to 4 words
            words = text.split()
            if len(words) > 4:
                text = " ".join(words[:4])
            return text
        except Exception as e:
            logger.warning(f"[Clusterer] Label generation failed: {e}")
            return UNCATEGORIZED_LABEL

    # ── Online assignment ─────────────────────────────────────────

    def assign_new_doc(self, doc_id: str) -> Tuple[str, str]:
        """Assign a freshly-ingested doc to the nearest existing cluster.

        Returns (cluster_id, cluster_label). Falls back to "uncategorized"
        when no centroid is available or no cluster crosses ASSIGN_THRESHOLD.

        Caller is expected to invoke from a background thread.
        """
        centroid = self.fetch_doc_centroid(doc_id, use_cache=False)

        with self._lock:
            # No real clusters yet → uncategorized
            real_clusters = [
                (cid, np.asarray(c.centroid, dtype=np.float32))
                for cid, c in self._clusters.items()
                if cid != UNCATEGORIZED_ID and c.centroid
            ]

            if centroid is None or not real_clusters:
                self._assignments[doc_id] = UNCATEGORIZED_ID
                if UNCATEGORIZED_ID in self._clusters:
                    self._clusters[UNCATEGORIZED_ID].doc_count += 1
                else:
                    self._clusters[UNCATEGORIZED_ID] = ClusterEntry(
                        cluster_id=UNCATEGORIZED_ID,
                        label=UNCATEGORIZED_LABEL,
                        centroid=[],
                        doc_count=1,
                    )
                self._persist_locked()
                logger.info(f"[Clusterer] {doc_id} → uncategorized (no match)")
                # Re-cluster trigger
                if self._should_recluster_locked():
                    threading.Thread(
                        target=self.cluster_all,
                        kwargs={"force": False},
                        daemon=True,
                    ).start()
                return UNCATEGORIZED_ID, UNCATEGORIZED_LABEL

            best_cid: Optional[str] = None
            best_sim = -1.0
            for cid, cvec in real_clusters:
                sim = _cosine(_l2_normalize(cvec), centroid)
                if sim > best_sim:
                    best_sim = sim
                    best_cid = cid

            if best_cid is not None and best_sim >= ASSIGN_THRESHOLD:
                entry = self._clusters[best_cid]
                # Move the centroid slightly toward the new doc (running mean).
                n = max(1, entry.doc_count)
                old_c = np.asarray(entry.centroid, dtype=np.float32)
                new_c = _l2_normalize((old_c * n + centroid) / (n + 1))
                entry.centroid = new_c.tolist()
                entry.doc_count += 1
                entry.doc_count_since_relabel += 1
                self._assignments[doc_id] = best_cid
                self._persist_locked()
                logger.info(
                    f"[Clusterer] {doc_id} → {best_cid} '{entry.label}' (sim={best_sim:.2f})"
                )

                # Incremental relabel if drift threshold hit
                if entry.doc_count_since_relabel >= RELABEL_AFTER_NEW_DOCS:
                    threading.Thread(
                        target=self._relabel_one,
                        args=(best_cid,),
                        daemon=True,
                    ).start()

                return best_cid, entry.label

            # Below threshold → uncategorized
            self._assignments[doc_id] = UNCATEGORIZED_ID
            if UNCATEGORIZED_ID in self._clusters:
                self._clusters[UNCATEGORIZED_ID].doc_count += 1
            else:
                self._clusters[UNCATEGORIZED_ID] = ClusterEntry(
                    cluster_id=UNCATEGORIZED_ID,
                    label=UNCATEGORIZED_LABEL,
                    centroid=[],
                    doc_count=1,
                )
            self._persist_locked()
            logger.info(
                f"[Clusterer] {doc_id} → uncategorized (best sim={best_sim:.2f})"
            )

            if self._should_recluster_locked():
                threading.Thread(
                    target=self.cluster_all,
                    kwargs={"force": False},
                    daemon=True,
                ).start()
            return UNCATEGORIZED_ID, UNCATEGORIZED_LABEL

    def _should_recluster_locked(self) -> bool:
        """Trigger re-cluster when uncategorized backlog grows past threshold."""
        uncat = self._clusters.get(UNCATEGORIZED_ID)
        if uncat and uncat.doc_count >= MIN_DOCS_FOR_CLUSTERING:
            return True
        return False

    def _relabel_one(self, cluster_id: str):
        """Generate a fresh label for a single cluster (drift compensation)."""
        try:
            from .document_registry import get_document_registry
            registry = get_document_registry()
        except Exception:
            return
        with self._lock:
            if cluster_id not in self._clusters:
                return
            members = [d for d, cid in self._assignments.items() if cid == cluster_id][:3]
            if not members:
                return
        label = self._generate_label(members, registry)
        with self._lock:
            entry = self._clusters.get(cluster_id)
            if entry and label:
                entry.label = label
                entry.doc_count_since_relabel = 0
                self._persist_locked()

    # ── Maintenance ────────────────────────────────────────────────

    def forget_doc(self, doc_id: str):
        """Remove a document from cluster bookkeeping (called on delete)."""
        with self._lock:
            cid = self._assignments.pop(doc_id, None)
            if cid and cid in self._clusters:
                self._clusters[cid].doc_count = max(0, self._clusters[cid].doc_count - 1)
                if self._clusters[cid].doc_count == 0 and cid != UNCATEGORIZED_ID:
                    self._clusters.pop(cid, None)
            self._centroid_cache.pop(doc_id, None)
            self._persist_locked()


# ── Module-level accessor ──────────────────────────────────────────


def get_clusterer() -> DocumentClusterer:
    """Get the singleton DocumentClusterer."""
    return DocumentClusterer()
