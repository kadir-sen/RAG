"""Semantic cache — reuse an answer for a PARAPHRASE of an earlier question.

The exact prompt-hash cache in llm_client only hits when the text is identical.
Real users rephrase constantly ("what delayed the drawings?" vs "why were the
drawings late?"). This layer embeds the query (free local fastembed) and serves a
prior result when cosine similarity clears a high bar, scoped by a `namespace`
signature so a changed file/table inventory never serves a stale answer.

Deliberately conservative: process-local, capped, high threshold. Used only for
low-risk, paraphrase-stable calls (query classification). Never used for SQL or
synthesis, where a paraphrase can legitimately need a different answer.
"""
from __future__ import annotations

import threading
from typing import Dict, List, Optional, Tuple

from .logger import logger

# namespace -> list of (vector, value). Process-local; warms up quickly.
_STORE: Dict[str, List[Tuple[List[float], str]]] = {}
_LOCK = threading.RLock()
_MAX_PER_NS = 500


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = sa = sb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        sa += x * x
        sb += y * y
    if sa <= 0 or sb <= 0:
        return -1.0
    return dot / ((sa ** 0.5) * (sb ** 0.5))


def embed_query(text: str) -> Optional[List[float]]:
    """Embed a query with the already-loaded local model (free). Returns None if
    no embed model is configured (so callers degrade to the exact cache only)."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        from llama_index.core import Settings
        model = Settings.embed_model
        if model is None:
            return None
        return model.get_text_embedding(text)
    except Exception as e:
        logger.debug(f"[SemanticCache] embed failed: {e}")
        return None


def lookup(namespace: str, vector: Optional[List[float]],
           threshold: float = 0.97) -> Optional[str]:
    """Return a cached value whose stored query is ≥ threshold similar, else None."""
    if not vector or not namespace:
        return None
    with _LOCK:
        entries = _STORE.get(namespace) or []
        best_val, best_sim = None, threshold
        for vec, val in entries:
            sim = _cosine(vector, vec)
            if sim >= best_sim:
                best_sim, best_val = sim, val
    if best_val is not None:
        logger.info(f"[SemanticCache] HIT ns={namespace[:8]} sim≈{best_sim:.3f}")
    return best_val


def put(namespace: str, vector: Optional[List[float]], value: str) -> None:
    if not vector or not namespace or value is None:
        return
    with _LOCK:
        entries = _STORE.setdefault(namespace, [])
        entries.append((vector, value))
        if len(entries) > _MAX_PER_NS:
            del entries[: len(entries) - _MAX_PER_NS]  # drop oldest
