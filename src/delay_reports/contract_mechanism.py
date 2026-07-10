"""Contract mechanism extraction — MVP (deterministic).

Reads the contract document(s) in the corpus and extracts the notice / EOT /
claim time-bar mechanisms it actually states — "notice within N days", the
governing sub-clause, and the trigger basis — so the notice compliance matrix
can use CLAUSE-DERIVED periods instead of assumed defaults.

Deterministic regex over retrieved contract text with a containment guard (the
period number and the quoted phrase must appear verbatim in the source chunk —
the model, if ever added, could not invent a period). Every mechanism carries
its clause ref, period, verbatim quote and source (file/page). This is an
extraction aid for an analyst, NOT legal advice: contracts amend and cross-
refer, so each extracted period must be verified against the executed contract.

No LLM. Never raises.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# "within 28 days" / "28 days of becoming aware" / "no later than 42 days"
_PERIOD_RE = re.compile(
    r"(?:within|no later than|not later than|within a period of)\s+"
    r"(\d{1,3})\s+days"
    r"|(\d{1,3})\s+days\s+(?:of|after|from|following|before)",
    re.IGNORECASE)
_CLAUSE_RE = re.compile(
    r"(?:sub[- ]?clause|clause|article|section|s\.)\s*"
    r"(\d{1,2}(?:\.\d{1,2}){0,3})", re.IGNORECASE)

_TYPE_KEYWORDS = {
    "eot": r"extension of time|\beot\b|prolongation",
    "notice": r"\bnotice\b|notify|shall give notice",
    "claim": r"\bclaim\b|entitlement",
}


@dataclass
class Mechanism:
    mechanism_type: str            # "notice" | "eot" | "claim"
    period_days: int
    clause_ref: str                # e.g. "20.1" or "" if none nearby
    basis: str                     # short trigger phrase, e.g. "of becoming aware"
    quote: str                     # verbatim excerpt containing the period
    file_name: str
    doc_id: str
    page_number: int
    confidence: str = "medium"     # "high" if clause_ref + type keyword present


@dataclass
class MechanismResult:
    mechanisms: List[Mechanism] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)
    contract_docs: int = 0


_STANDING_CAVEATS = [
    "Notice periods are extracted from the contract text as written; contracts "
    "amend and cross-refer, so each period must be verified against the "
    "executed conditions of contract before it is relied on.",
    "This is an extraction aid for analyst review, not legal advice or an "
    "interpretation of the parties' rights.",
]


def _window(text: str, start: int, end: int, pad: int = 90) -> str:
    return " ".join(text[max(0, start - pad):min(len(text), end + pad)].split())


def _sentence_bounds(text: str, pos: int) -> tuple[int, int]:
    """Bounds of the sentence containing `pos`. Boundary = '. ' (period+space)
    so decimals in clause numbers (20.1, 8.4) do not split a sentence."""
    s = text.rfind(". ", 0, pos)
    start = s + 2 if s != -1 else 0
    e = text.find(". ", pos)
    end = e if e != -1 else len(text)
    return start, end


def _classify(text: str, pos: int) -> str:
    """Mechanism type from the keyword in the SAME sentence as the period,
    nearest first; falls back to the nearest keyword overall, else 'notice'."""
    start, end = _sentence_bounds(text, pos)
    sentence = text[start:end]
    for scope, ref in ((sentence, pos - start), (text, pos)):
        best_type, best_d = None, 10**9
        for mtype, pat in _TYPE_KEYWORDS.items():
            for mm in re.finditer(pat, scope, re.IGNORECASE):
                d = abs(mm.start() - ref)
                if d < best_d and d <= 260:
                    best_d, best_type = d, mtype
        if best_type:
            return best_type
    return "notice"


def _nearest_clause(text: str, pos: int) -> str:
    """The clause reference closest before `pos` (contracts state the clause
    then the period)."""
    best = ""
    best_d = 10**9
    for m in _CLAUSE_RE.finditer(text):
        d = pos - m.start()
        if 0 <= d < best_d:
            best_d, best = d, m.group(1)
    return best if best_d <= 400 else ""


def extract_from_text(pages: Dict[int, str], file_name: str, doc_id: str
                      ) -> List[Mechanism]:
    """Extract notice/EOT/claim periods from one document's text-by-page."""
    out: List[Mechanism] = []
    seen: set = set()
    for page, text in (pages or {}).items():
        text = text or ""
        for m in _PERIOD_RE.finditer(text):
            days = m.group(1) or m.group(2)
            try:
                n = int(days)
            except (TypeError, ValueError):
                continue
            if not (1 <= n <= 365):
                continue
            quote = _window(text, m.start(), m.end())
            context = _window(text, m.start(), m.end(), pad=160)
            # containment guard: the period + phrase must be in the source text
            if f"{n}" not in quote or quote.lower() not in " ".join(
                    text.split()).lower():
                continue
            mtype = _classify(text, m.start())
            clause = _nearest_clause(text, m.start())
            key = (mtype, n, clause)
            if key in seen:
                continue
            seen.add(key)
            basis_m = re.search(
                r"days\s+(of|after|from|following|before)\s+([a-z ]{3,40})",
                context, re.IGNORECASE)
            basis = (basis_m.group(0) if basis_m else "").strip()[:60]
            out.append(Mechanism(
                mechanism_type=mtype, period_days=n, clause_ref=clause,
                basis=basis, quote=quote[:240], file_name=file_name,
                doc_id=doc_id, page_number=int(page) if page else 0,
                confidence="high" if clause and mtype != "notice" or
                (clause and re.search(_TYPE_KEYWORDS[mtype], context, re.I))
                else "medium"))
    return out


def get_contract_mechanisms(corpus: str = "",
                            doc_ids: Optional[List[str]] = None
                            ) -> MechanismResult:
    """Retrieve contract chunks and extract their mechanisms. Best-effort."""
    result = MechanismResult()
    try:
        from src.document_rag import get_document_rag
        rag = get_document_rag()
        out = rag.query("notice period extension of time claim within days",
                        top_k=25, doc_ids=doc_ids,
                        payload_filters={"doc_type": "contract"},
                        synthesize=False)
        sources = out.get("sources") or []
    except Exception as e:
        logger.debug(f"[ContractMechanism] retrieval degraded: {e}")
        sources = []

    # Group retrieved chunks into per-doc page text.
    per_doc: Dict[str, Dict[int, str]] = {}
    names: Dict[str, str] = {}
    for s in sources:
        fn = s.get("file_name", "") or s.get("doc_id", "")
        doc_id = s.get("doc_id", "") or fn
        page = int(s.get("page_number", 0) or 0)
        text = s.get("text") or s.get("text_snippet") or s.get("snippet") or ""
        if not text:
            continue
        per_doc.setdefault(doc_id, {}).setdefault(page, "")
        per_doc[doc_id][page] += " " + text
        names[doc_id] = fn
    result.contract_docs = len(per_doc)
    for doc_id, pages in per_doc.items():
        result.mechanisms.extend(
            extract_from_text(pages, names.get(doc_id, doc_id), doc_id))

    result.caveats = list(_STANDING_CAVEATS)
    if not per_doc:
        result.caveats.insert(0, "No contract document was found in the corpus "
                              "(doc_type='contract'); upload the conditions of "
                              "contract to extract notice periods.")
    return result


def notice_rules_from_mechanisms(mechs: List[Mechanism]) -> Dict[str, int]:
    """Build notice_matrix rules from extracted mechanisms. notice/eot → period.
    Empty dict if nothing usable (caller falls back to assumed defaults)."""
    rules: Dict[str, int] = {}
    for m in mechs:
        if m.mechanism_type in ("notice", "eot"):
            rules.setdefault("default", m.period_days)
            rules[m.mechanism_type] = m.period_days
            if m.mechanism_type == "eot":
                rules["extension of time"] = m.period_days
    return rules
