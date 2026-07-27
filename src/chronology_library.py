"""The curated chronologies, and how a typed subject is matched to one.

A subject typed into the chronology chat bar resolves to one of the authored
chronologies in data/chronologies/ and its narrative is shown in full. The
matching is deliberately **not** an LLM call: these documents are the record,
the mapping from subject to document is a fixed one, and a model that
occasionally picks the wrong chronology for a dispute is worse than useless.
Token scoring with phrase bonuses is enough to let someone type "the
procurement risk transfer" or "wiesbaden" and land on the contract-strategy
chronology without knowing its title.

Ported from delay-disputes-portal/assets/js/chronology-library.js — same
weights, same thresholds, same three outcomes — so the portal's builder and
this area agree on what a subject means.

TO ADD A CHRONOLOGY
  1. Drop the .docx in data/chronologies/
  2. Add an entry to _DOCS below: ref, title, file, summary, keywords
Keywords outweigh the title, so put the words people actually type in there —
abbreviations, party names, synonyms.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .config import BASE_DIR
from .logger import logger

CHRONOLOGY_DIR = BASE_DIR / "data" / "chronologies"

COLLECTION = "Edinburgh Tram Network — Delay and Prolongation"


@dataclass
class ChronologyDoc:
    ref: str
    title: str
    file: str
    summary: str
    keywords: List[str] = field(default_factory=list)


_DOCS: List[ChronologyDoc] = [
    ChronologyDoc(
        ref="01",
        title="Incomplete and Misaligned Design (The SDS Contract)",
        file="01-design-sds.docx",
        summary=("The SDS design contract with Parsons Brinckerhoff — scope, "
                 "co-ordination and the late and incomplete design deliverables."),
        keywords=[
            "design", "designs", "designer", "sds", "system design services",
            "incomplete design", "misaligned design", "design contract",
            "parsons brinckerhoff", "scott wilson", "mott macdonald", "atkins",
            "drawings", "coordination", "co-ordination", "uncoordinated",
            "consents", "approvals", "design deliverables", "late design",
            "design development", "scope of services", "tenderers",
        ],
    ),
    ChronologyDoc(
        ref="02",
        title="Mismanagement by Transport Initiatives Edinburgh (tie)",
        file="02-tie-mismanagement.docx",
        summary=("tie as delivery vehicle — governance layering, board conduct, "
                 "cost estimating and the Audit Scotland reviews."),
        keywords=[
            "tie", "transport initiatives edinburgh", "mismanagement",
            "management", "governance", "client", "delivery vehicle",
            "cec", "city of edinburgh council", "council", "tel", "board",
            "audit scotland", "project estimate", "business case",
            "arms length", "organisation", "reporting", "executive chairman",
        ],
    ),
    ChronologyDoc(
        ref="03",
        title="Utility Diversion Failures (MUDFA)",
        file="03-mudfa-utilities.docx",
        summary=("The Multi-Utilities Diversion Framework Agreement — scope "
                 "growth, unforeseen apparatus and the diversion programme."),
        keywords=[
            "mudfa", "utility", "utilities", "diversion", "diversions",
            "apparatus", "statutory undertakers", "carillion", "alfred mcalpine",
            "unforeseen", "trial holes", "services", "ducts", "mains",
            "utility diversion", "diversion works", "gas", "water", "electricity",
        ],
    ),
    ChronologyDoc(
        ref="04",
        title="Flawed Contract Strategy and Risk Transfer",
        file="04-contract-strategy.docx",
        summary=("The Infraco contract strategy — fixed price ambitions, the "
                 "pricing assumptions and where the risk actually sat."),
        keywords=[
            "contract strategy", "risk transfer", "procurement", "infraco",
            "fixed price", "lump sum", "pricing", "schedule 4", "notified departure",
            "bilfinger", "siemens", "caf", "consortium", "wiesbaden",
            "risk allocation", "tender", "novation", "flawed strategy",
        ],
    ),
    ChronologyDoc(
        ref="05",
        title="Contractor Disputes and Adjudications",
        file="05-contractor-disputes.docx",
        summary=("The disputes with the Infraco consortium — notified "
                 "departures, adjudications and the mediation at Mar Hall."),
        keywords=[
            "dispute", "disputes", "adjudication", "adjudications", "claim",
            "claims", "mediation", "mar hall", "settlement", "dsp",
            "dispute resolution", "contractor", "consortium", "escalation",
            "commercial", "entitlement", "arbitration",
        ],
    ),
    ChronologyDoc(
        ref="06",
        title="National Oversight and Public Scrutiny",
        file="06-national-oversight.docx",
        summary=("Scottish Government, Transport Scotland and parliamentary "
                 "scrutiny of the project."),
        keywords=[
            "oversight", "scrutiny", "scottish government", "transport scotland",
            "parliament", "parliamentary", "ministers", "minister", "public",
            "committee", "inquiry", "audit", "grant", "funding", "national",
        ],
    ),
]


# ── matching ────────────────────────────────────────────────────────────
# Being wrong is worse than asking: handing over the chronology for the wrong
# issue is a real problem, so a close second forces a question rather than a
# guess.
_CONFIDENT = 0.60   # below this nothing is offered outright
_MARGIN = 0.15      # the winner must beat the runner-up by this

_TITLE_WEIGHT = 0.6
_KEYWORD_WEIGHT = 1.0
_STOP = {
    "the", "a", "an", "of", "and", "or", "for", "to", "in", "on", "at", "by",
    "with", "about", "is", "was", "were", "be", "that", "this", "it", "its",
    "chronology", "history", "timeline", "show", "me", "give", "tell", "what",
    "happened",
}


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())


def _tokenise(text: str) -> List[str]:
    return [t for t in _normalise(text).split() if t and t not in _STOP]


def _terms(doc: ChronologyDoc) -> List[tuple]:
    """(word, weight) pairs — keywords outweigh title words."""
    out = [(w, _TITLE_WEIGHT) for w in _tokenise(doc.title)]
    for kw in doc.keywords:
        out.extend((w, _KEYWORD_WEIGHT) for w in _tokenise(kw))
    return out


def _phrases(doc: ChronologyDoc) -> List[str]:
    return [_normalise(k).strip() for k in doc.keywords] + [_normalise(doc.title).strip()]


def _term_score(query_token: str, terms: List[tuple]) -> float:
    """Best match for one query word: exact, shared stem, then substring."""
    best = 0.0
    for word, weight in terms:
        if word == query_token:
            s = weight
        elif len(query_token) >= 4 and (word.startswith(query_token) or query_token.startswith(word)):
            # "utilities" ~ "utility", "disputes" ~ "dispute"
            s = weight * 0.75
        elif len(query_token) >= 5 and query_token in word:
            s = weight * 0.5
        else:
            continue
        best = max(best, s)
    return best


def score(query: str, doc: ChronologyDoc) -> float:
    tokens = _tokenise(query)
    if not tokens:
        return 0.0
    terms = _terms(doc)
    base = sum(_term_score(t, terms) for t in tokens) / len(tokens)

    # A phrase typed as a phrase is a much stronger signal than its words apart.
    norm = _normalise(query)
    bonus = 0.0
    for p in _phrases(doc):
        if " " in p and p in norm:
            bonus = max(bonus, 0.35 + len(p.split()) * 0.08)
    return base + bonus


def match(query: str) -> Dict:
    """Resolve a typed subject.

    Returns {"status": "match"|"ambiguous"|"none", ...}:
      match      one clear winner        → show it
      ambiguous  two or more close       → ask which
      none       nothing scored well     → offer the list
    """
    ranked = sorted(
        ({"doc": d, "score": round(score(query, d), 4)} for d in _DOCS),
        key=lambda r: r["score"],
        reverse=True,
    )
    if not ranked or ranked[0]["score"] < _CONFIDENT:
        return {"status": "none", "ranked": ranked}

    best = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    if second and (best["score"] - second["score"]) < _MARGIN:
        close = [r for r in ranked if r["score"] >= best["score"] - _MARGIN]
        return {"status": "ambiguous", "ranked": close}
    return {"status": "match", "doc": best["doc"], "score": best["score"], "ranked": ranked}


# ── reading the documents ───────────────────────────────────────────────
_cache: Dict[str, List[Dict]] = {}
_lock = threading.Lock()


def _parse_docx(path: Path) -> List[Dict]:
    """A .docx chronology → its numbered entries.

    The authored files are flat paragraphs: two header lines, a title, then
    numbered entries ("6.1.1 On 29 March 2005, tie issued…") with lettered
    sub-points ("i)", "ii)"). Split on that numbering so the UI can render an
    entry per paragraph rather than one wall of text.
    """
    from docx import Document  # local import: only this path needs python-docx

    entries: List[Dict] = []
    for para in Document(str(path)).paragraphs:
        text = (para.text or "").strip()
        if not text:
            continue
        m = re.match(r"^(\d+(?:\.\d+)+)\s*(.*)$", text)
        if m:
            entries.append({"ref": m.group(1), "text": m.group(2).strip(), "sub": []})
        elif re.match(r"^[ivx]+\)", text, re.I) and entries:
            entries[-1]["sub"].append(re.sub(r"^[ivx]+\)\s*", "", text, flags=re.I))
        elif entries:
            # A continuation line of the entry above.
            entries[-1]["text"] = (entries[-1]["text"] + " " + text).strip()
    return entries


def get_entries(ref: str) -> List[Dict]:
    """Parsed entries for one chronology, cached after the first read."""
    doc = next((d for d in _DOCS if d.ref == ref), None)
    if doc is None:
        return []
    with _lock:
        if ref in _cache:
            return _cache[ref]
    path = CHRONOLOGY_DIR / doc.file
    try:
        entries = _parse_docx(path)
    except Exception as e:
        logger.warning(f"[Chronology] could not read {doc.file}: {e}")
        entries = []
    with _lock:
        _cache[ref] = entries
    return entries


def get_doc(ref: str) -> Optional[ChronologyDoc]:
    return next((d for d in _DOCS if d.ref == ref), None)


def list_docs() -> List[ChronologyDoc]:
    return list(_DOCS)
