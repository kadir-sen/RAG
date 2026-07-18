"""Deterministic-first reranker for RAG candidates (Sprint B).

Vector similarity alone mis-orders evidence: the top dense hit is often a
near-duplicate of the second, a wrong-project page can outscore the right one,
and a date-bounded question retrieves out-of-window pages. This module re-orders
a fused candidate pool with signals the vector score can't see — exact
phrase/entity/date matches, wrong project/date/doc-type penalties — and
diversifies with MMR so the final set isn't three copies of one page.

Three tiers, composed by strategy:
  * Tier 1 — deterministic (always available, no model, ~0 RAM). The reliable
    default and the fallback for every other tier.
  * Tier 2 — cross-encoder (optional, ENABLE_CROSS_ENCODER). Pluggable; if the
    model can't load it silently degrades to Tier 1.
  * Tier 3 — the existing LLM reranker lives in document_rag; this module never
    calls an LLM.

Candidates are the fused node dicts produced by rrf_fuse (keys: key, doc_id,
file_name, file_path, page_number, total_pages, text, dense_score?, rrf?). They
are returned reordered and annotated with `rerank_score` and `why_selected`;
the input dicts are not mutated.

Pure and deterministic (Tier 1): no network, no clock, no randomness — so it is
unit-testable and safe on the constrained box.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

_WORD = re.compile(r"[a-z0-9]+")
# ISO-ish and common construction date shapes, e.g. 2024-03-01, 01/03/2024, 1 Mar 2024
_DATE_RE = re.compile(
    r"\b(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{2,4}|"
    r"\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}\s+\d{4})\b")

# Scoring weights. The base (vector/fused) signal is rank-normalized to [0,1]
# across the candidate set and weighted so it no longer *dominates*: strong
# lexical evidence (query-term coverage, exact phrase) can overturn a large
# vector lead — that is the whole point of reranking. Entity/date matches
# promote; wrong project/doc-type demote hard.
_W_BASE = 0.40            # normalized vector/fused signal
_W_COVERAGE = 0.45        # fraction of query terms present in the passage
_W_TERM_OVERLAP = 0.15    # Jaccard (secondary lexical signal)
_W_PHRASE = 0.25
_W_ENTITY = 0.20
_W_DATE_IN_RANGE = 0.20
_P_WRONG_DOCTYPE = 0.45   # penalty (> max base contribution, so it overrides rank)
_P_WRONG_PROJECT = 0.60   # penalty (strong: never cite another project's page)


@dataclass
class EvidenceCandidate:
    """A reranked, citation-ready evidence packet."""
    document_id: str
    document_name: str
    page: int
    snippet: str
    score: float                       # pre-rerank fused/dense score (0..1-ish)
    rerank_score: float
    why_selected: List[str] = field(default_factory=list)
    date: Optional[str] = None
    citation: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "document_name": self.document_name,
            "page": self.page,
            "date": self.date,
            "snippet": self.snippet,
            "score": round(self.score, 4),
            "rerank_score": round(self.rerank_score, 4),
            "why_selected": self.why_selected,
            "citation": self.citation,
        }


# ── helpers ────────────────────────────────────────────────

def _tokens(text: str) -> List[str]:
    return _WORD.findall((text or "").lower())


def _token_set(text: str) -> set:
    return set(_tokens(text))


def _base_score(c: Dict[str, Any]) -> float:
    """Normalize whatever ranking signal the candidate carries into ~0..1.

    rrf scores are tiny (~1/60); dense scores are already ~0..1. We only need a
    stable ordering base, so map rrf into a comparable band by its rank later —
    here take the best available raw signal.
    """
    for k in ("rerank_base", "dense_score", "score"):
        v = c.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    rrf = c.get("rrf")
    if isinstance(rrf, (int, float)):
        # rrf ~ [0, ~0.2]; scale up so it lands in a sane band
        return float(rrf) * 5.0
    return 0.0


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / len(a | b)


def _citation(name: str, page: Any) -> str:
    try:
        p = int(page)
    except (TypeError, ValueError):
        p = 1
    return f"{name}, p.{p}" if name else f"p.{p}"


def _extract_dates(text: str) -> List[str]:
    return _DATE_RE.findall(text or "")


def _in_range(dates: Sequence[str], date_range: Optional[Tuple[str, str]]) -> bool:
    """Best-effort: does any extracted date fall within [start, end]?

    Dates are compared as normalized strings when parseable; unparseable dates
    never match (so a date filter never invents a hit)."""
    if not date_range or not dates:
        return False
    start, end = date_range
    s, e = _norm_date(start), _norm_date(end)
    if s is None or e is None:
        return False
    for d in dates:
        nd = _norm_date(d)
        if nd is not None and s <= nd <= e:
            return True
    return False


def _norm_date(s: Any) -> Optional[str]:
    """Normalize a handful of date shapes to a sortable YYYY-MM-DD-ish string.

    Deterministic and dependency-free; returns None when it can't parse (the
    caller treats None as 'no match', never as a wildcard)."""
    if not s:
        return None
    s = str(s).strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m:
        y, mo, d = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", s)
    if m:
        d, mo, y = m.groups()
        y = y if len(y) == 4 else ("20" + y)
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    m = re.match(r"^(\d{4})-(\d{1,2})$", s)
    if m:
        y, mo = m.groups()
        return f"{y}-{int(mo):02d}-01"
    return None


# ── Tier 1: deterministic scoring ──────────────────────────

def _score_candidate(c: Dict[str, Any], norm_base: float, q_tokens: set,
                     q_phrases: List[str], entities: Optional[List[str]],
                     date_range: Optional[Tuple[str, str]],
                     doc_types: Optional[List[str]],
                     project: Optional[str]) -> Tuple[float, List[str]]:
    text = c.get("text") or c.get("snippet") or ""
    text_l = text.lower()
    why: List[str] = []
    score = _W_BASE * norm_base

    c_tokens = _token_set(text)
    # Query-term coverage: fraction of the query's terms that appear in the
    # passage — the strongest lexical signal for overturning a bad vector order.
    if q_tokens:
        coverage = len(q_tokens & c_tokens) / len(q_tokens)
        if coverage > 0:
            score += _W_COVERAGE * coverage
            if coverage >= 0.5:
                why.append("term coverage")
    overlap = _jaccard(q_tokens, c_tokens)
    if overlap > 0:
        score += _W_TERM_OVERLAP * overlap

    for ph in q_phrases:
        if ph and ph in text_l:
            score += _W_PHRASE
            why.append("exact phrase")
            break

    if entities:
        hit = [e for e in entities if e and e.lower() in text_l]
        if hit:
            score += _W_ENTITY * min(len(hit), 3)
            why.append(f"entity: {hit[0]}")

    if date_range:
        if _in_range(_extract_dates(text), date_range):
            score += _W_DATE_IN_RANGE
            why.append("date in range")

    # Penalties — wrong project / wrong doc type demote strongly.
    if project:
        cand_project = str(c.get("project") or "").lower()
        if cand_project and cand_project != project.lower():
            score -= _P_WRONG_PROJECT
            why.append("penalty: wrong project")
    if doc_types:
        cand_dt = str(c.get("doc_type") or "").lower()
        wanted = {d.lower() for d in doc_types if d}
        if cand_dt and wanted and cand_dt not in wanted:
            score -= _P_WRONG_DOCTYPE
            why.append("penalty: wrong doc type")

    return score, why


def _mmr_order(scored: List[Tuple[float, Dict[str, Any], List[str]]],
               top_k: int, lam: float) -> List[Tuple[float, Dict[str, Any], List[str]]]:
    """Maximal Marginal Relevance selection: balance relevance against
    redundancy so the final set isn't several near-identical pages.

    Deterministic: ties broken by original (already relevance-sorted) order."""
    if top_k <= 0 or not scored:
        return []
    remaining = list(scored)
    remaining.sort(key=lambda t: t[0], reverse=True)
    selected: List[Tuple[float, Dict[str, Any], List[str]]] = []
    sel_token_sets: List[set] = []
    while remaining and len(selected) < top_k:
        best_idx = 0
        best_val = None
        for i, (rel, cand, why) in enumerate(remaining):
            cand_tokens = _token_set(cand.get("text") or cand.get("snippet") or "")
            redundancy = max((_jaccard(cand_tokens, s) for s in sel_token_sets),
                             default=0.0)
            mmr = lam * rel - (1.0 - lam) * redundancy
            if best_val is None or mmr > best_val:
                best_val = mmr
                best_idx = i
        chosen = remaining.pop(best_idx)
        selected.append(chosen)
        sel_token_sets.append(_token_set(chosen[1].get("text")
                                         or chosen[1].get("snippet") or ""))
    return selected


# ── public API ─────────────────────────────────────────────

def rerank_candidates(query: str, candidates: List[Dict[str, Any]],
                      entities: Optional[List[str]] = None,
                      date_range: Optional[Tuple[str, str]] = None,
                      doc_types: Optional[List[str]] = None,
                      project: Optional[str] = None,
                      top_k: int = 12,
                      strategy: str = "hybrid") -> List[Dict[str, Any]]:
    """Rerank fused RAG candidates. Returns reordered dicts annotated with
    `rerank_score` and `why_selected`. Never raises — on any internal error it
    returns the input truncated to top_k (the fused order), so retrieval never
    fails because reranking did.

    strategy: "deterministic" (Tier 1 only) | "hybrid" (Tier 1 + optional
    cross-encoder blend when ENABLE_CROSS_ENCODER). The LLM tier is not invoked
    here.
    """
    if not candidates:
        return []
    try:
        from ..config import RERANK_MMR_LAMBDA, ENABLE_CROSS_ENCODER
        lam = RERANK_MMR_LAMBDA
    except Exception:
        lam, ENABLE_CROSS_ENCODER = 0.7, False

    try:
        q_tokens = _token_set(query)
        q_l = (query or "").lower().strip()
        # phrases: the whole query and any quoted spans
        q_phrases = [q_l] if len(q_l) >= 4 else []
        q_phrases += [m.strip('"').lower() for m in re.findall(r'"([^"]+)"', query or "")]

        # Rank-normalize the base signal across the set so it informs but does
        # not dominate (equal scores → neutral 0.5).
        bases = [_base_score(c) for c in candidates]
        lo, hi = min(bases), max(bases)
        span = hi - lo

        scored: List[Tuple[float, Dict[str, Any], List[str]]] = []
        for c, b in zip(candidates, bases):
            norm_base = 0.5 if span <= 0 else (b - lo) / span
            s, why = _score_candidate(c, norm_base, q_tokens, q_phrases, entities,
                                      date_range, doc_types, project)
            scored.append((s, c, why))

        # Optional Tier 2: cross-encoder blend (best-effort, degrades to Tier 1).
        if strategy == "hybrid" and ENABLE_CROSS_ENCODER:
            scored = _blend_cross_encoder(query, scored)

        ordered = _mmr_order(scored, top_k, lam)

        out: List[Dict[str, Any]] = []
        for rank, (s, c, why) in enumerate(ordered):
            d = dict(c)
            d["rerank_score"] = round(float(s), 4)
            d["why_selected"] = why or (["fused rank"] if rank == 0 else [])
            out.append(d)
        return out
    except Exception as e:  # pragma: no cover - safety net
        logger.warning(f"[reranker] failed → fused order: {e}")
        return candidates[:top_k]


def _blend_cross_encoder(query: str,
                         scored: List[Tuple[float, Dict[str, Any], List[str]]]
                         ) -> List[Tuple[float, Dict[str, Any], List[str]]]:
    """Blend a cross-encoder relevance score into the deterministic score.

    Pluggable and fully optional: if the model can't be loaded (missing dep,
    RAM), we log once and return the deterministic scores unchanged."""
    try:
        model = _get_cross_encoder()
        if model is None:
            return scored
        pairs = [(query, c.get("text") or c.get("snippet") or "")
                 for _, c, _ in scored]
        ce_scores = model.predict(pairs)
        blended = []
        for (s, c, why), ce in zip(scored, ce_scores):
            blended.append((s + 0.5 * float(ce), c, why + ["cross-encoder"]))
        return blended
    except Exception as e:  # pragma: no cover - optional path
        logger.warning(f"[reranker] cross-encoder skipped: {e}")
        return scored


_CE_MODEL = None
_CE_TRIED = False


def _get_cross_encoder():  # pragma: no cover - optional heavy path
    """Lazy singleton cross-encoder. Returns None if unavailable."""
    global _CE_MODEL, _CE_TRIED
    if _CE_TRIED:
        return _CE_MODEL
    _CE_TRIED = True
    try:
        from ..config import CROSS_ENCODER_MODEL
        from sentence_transformers import CrossEncoder
        _CE_MODEL = CrossEncoder(CROSS_ENCODER_MODEL)
        logger.info(f"[reranker] cross-encoder loaded: {CROSS_ENCODER_MODEL}")
    except Exception as e:
        logger.info(f"[reranker] cross-encoder unavailable ({e}); Tier 1 only")
        _CE_MODEL = None
    return _CE_MODEL


def to_evidence_packet(candidate: Dict[str, Any]) -> EvidenceCandidate:
    """Normalize a (reranked) candidate dict into a citation-ready packet."""
    name = candidate.get("file_name") or candidate.get("document_name") or ""
    page = candidate.get("page_number") or candidate.get("page") or 1
    snippet = candidate.get("text") or candidate.get("snippet") or ""
    return EvidenceCandidate(
        document_id=candidate.get("doc_id") or candidate.get("document_id") or name,
        document_name=name,
        page=int(page) if str(page).isdigit() else 1,
        snippet=snippet[:500],
        score=_base_score(candidate),
        rerank_score=float(candidate.get("rerank_score", 0.0)),
        why_selected=list(candidate.get("why_selected") or []),
        date=candidate.get("doc_date") or candidate.get("date"),
        citation=_citation(name, page),
        raw=candidate,
    )
