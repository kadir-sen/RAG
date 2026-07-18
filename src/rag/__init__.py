"""RAG retrieval helpers (Sprint B).

Public surface:
  rerank_candidates(...)  — deterministic-first reranker (entity/date/doc-type
                            boosts + MMR), optional pluggable cross-encoder.
  to_evidence_packet(...) — normalize a reranked candidate into a cited packet.
"""

from .reranker import (EvidenceCandidate, rerank_candidates,
                       to_evidence_packet)

__all__ = ["rerank_candidates", "to_evidence_packet", "EvidenceCandidate"]
