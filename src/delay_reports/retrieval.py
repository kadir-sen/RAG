"""Evidence retrieval for a named delay event — corpus-aware.

demo:      notice metadata (light_graph, trusted date/sender) ∪ hybrid RAG
edinburgh: hybrid RAG only. doc_date/sender stay None — the vector payload's
           `date` is the inquiry PUBLICATION date and must never leak into the
           chronology as an event date.
"""

from __future__ import annotations

import logging
from typing import Any, List

from .schemas import EvidenceItem, ScopeResult

logger = logging.getLogger(__name__)

_MAX_ITEMS = 40
_RAG_TOP_K = 25


def _add(items: List[EvidenceItem], seen: set, **kw) -> None:
    key = (kw.get("file_name"), kw.get("page_number"))
    if key in seen or len(items) >= _MAX_ITEMS:
        return
    seen.add(key)
    items.append(EvidenceItem(evidence_id=f"E{len(items) + 1}", **kw))


def retrieve_evidence(scope: ScopeResult, corpus: str,
                      doc_ids: Any = None) -> List[EvidenceItem]:
    """Gather up to 40 deduped evidence snippets. Never raises."""
    items: List[EvidenceItem] = []
    seen: set = set()
    title = scope.event_title or ""

    # ── Demo corpus: trusted notice metadata first ──
    if (corpus or "demo") == "demo" and scope.topic_terms:
        try:
            from src.light_graph import get_light_graph
            graph = get_light_graph()
            for node in graph.search_broad(scope.topic_terms, limit=20) or []:
                _add(items, seen,
                     file_name=node.get("file_name") or "",
                     doc_id=node.get("doc_id") or node.get("file_name") or "",
                     page_number=1,
                     snippet=" — ".join(filter(None, [
                         str(node.get("date") or ""),
                         f"From {node.get('sender')}" if node.get("sender") else "",
                         f"to {node.get('recipient')}" if node.get("recipient") else "",
                         str(node.get("subject") or ""),
                         " ".join(node.get("actions") or []),
                     ])),
                     doc_date=node.get("date"),
                     sender=node.get("sender"),
                     origin="graph")
        except Exception as e:
            logger.debug(f"[DelayReports] light_graph retrieval skipped: {e}")

    # ── Hybrid RAG retrieve-only (both corpora) ──
    try:
        from src.document_rag import get_document_rag
        rag = get_document_rag()
        # Rerank hints: promote the event's topic entities and, when the scope is
        # date-bounded, penalize out-of-window pages — precision that matters most
        # for a dated chronology. Payload dates are still never trusted as event
        # dates (that guard is downstream); this only reorders retrieval.
        rerank_hints: dict = {}
        if scope.topic_terms:
            rerank_hints["entities"] = scope.topic_terms
        if scope.date_from and scope.date_to:
            rerank_hints["date_range"] = (scope.date_from, scope.date_to)
        queries = [title]
        if scope.topic_terms:
            queries.append(" ".join(scope.topic_terms) +
                           " delay notice correspondence")
        for q in queries:
            if not q.strip() or len(items) >= _MAX_ITEMS:
                continue
            res = rag.query(q, top_k=_RAG_TOP_K, doc_ids=doc_ids,
                            synthesize=False,
                            rerank_hints=rerank_hints or None) or {}
            for s in res.get("sources") or []:
                if not isinstance(s, dict):
                    continue
                text = s.get("text") or s.get("text_snippet") or ""
                if not text.strip():
                    continue
                _add(items, seen,
                     file_name=s.get("file_name") or "",
                     doc_id=s.get("doc_id") or s.get("file_name") or "",
                     page_number=int(s.get("page_number") or 1),
                     snippet=text,
                     doc_date=None,   # NEVER trust payload dates here
                     sender=None,
                     origin="rag")
    except Exception as e:
        logger.warning(f"[DelayReports] RAG retrieval failed: {e}")

    return items
