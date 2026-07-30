"""The curated chronologies, and how a typed subject is matched to one.

A subject typed into the chronology chat bar resolves to one of the authored
chronologies in content/chronologies/ and its narrative is shown in full. The
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
  1. Drop the .docx in content/chronologies/
  2. Add an entry to _DOCS below: ref, title, file, summary, keywords
  3. Set download_name to the name the file should arrive under — the author's
     own name for it, not the numbered one we store it under.
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

# Under content/, not data/: docker-compose.prod.yml bind-mounts ./data over
# /app/data, so anything the image ships there is invisible once the container
# runs. These are authored content that travels with the build, not user data.
CHRONOLOGY_DIR = BASE_DIR / "content" / "chronologies"

COLLECTION = "Edinburgh Tram Network — Delay and Prolongation"


@dataclass
class ChronologyDoc:
    ref: str
    title: str
    file: str
    summary: str
    keywords: List[str] = field(default_factory=list)
    # We store these under numbered names so the set stays ordered on disk; the
    # author knows them by their own titles, and that is what a download should
    # be called — the file goes straight into a report. No extension: it comes
    # from `file`, so the suffix lives in one place.
    download_name: str = ""


_DOCS: List[ChronologyDoc] = [
    ChronologyDoc(
        ref="01",
        title="Incomplete and Misaligned Design (The SDS Contract)",
        file="01-design-sds.docx",
        download_name="Incomplete and Misaligned Design (The SDS Contract)",
        summary=("The SDS design contract with Parsons Brinckerhoff — scope, "
                 "co-ordination and the late and incomplete design deliverables."),
        keywords=[
            # the design itself
            "design", "designs", "designer", "incomplete design",
            "misaligned design", "design contract", "design deliverables",
            "late design", "design development", "design programme",
            "base date design", "drawings", "coordination", "co-ordination",
            "uncoordinated", "consents", "approvals",
            # the contract and who held it — these are what identify 01
            "sds", "system design services", "scope of services", "novation",
            "parsons brinckerhoff", "scott wilson", "mott macdonald", "atkins",
            "tenderers",
        ],
    ),
    ChronologyDoc(
        ref="02",
        title="Mismanagement by Transport Initiatives Edinburgh (tie)",
        file="02-tie-mismanagement.docx",
        # (TIE), not the (tie) of the title — the author capitalises it in the
        # file name, and the title's casing is what the matcher tokenises.
        download_name="Mismanagement by Transport Initiatives Edinburgh (TIE)",
        summary=("tie as delivery vehicle — governance layering, board conduct, "
                 "cost estimating and the Audit Scotland reviews."),
        keywords=[
            "tie", "transport initiatives edinburgh", "mismanagement",
            "management", "governance", "client", "delivery vehicle",
            "arms length", "organisation", "reporting", "executive chairman",
            # the bodies and reviews that only 02 is about
            "board", "audit scotland", "deloitte", "business case",
            "project estimate", "estimating", "cost estimate",
            "city of edinburgh council", "council",
        ],
    ),
    ChronologyDoc(
        ref="03",
        title="Utility Diversion Failures (MUDFA)",
        file="03-mudfa-utilities.docx",
        download_name="Utility Diversion Failures (MUDFA)",
        summary=("The Multi-Utilities Diversion Framework Agreement — scope "
                 "growth, unforeseen apparatus and the diversion programme."),
        keywords=[
            "mudfa", "multi utilities diversion framework agreement",
            "utility", "utilities", "utility diversion", "diversion",
            "diversions", "diversion works",
            "apparatus", "underground", "services", "ducts", "cables", "mains",
            "excavation", "streetworks", "trial holes", "unforeseen",
            "statutory undertakers",
            # the contractor that only 03 is about
            "carillion", "alfred mcalpine", "mcalpine", "amis",
        ],
    ),
    ChronologyDoc(
        ref="04",
        title='An "Irreparably Flawed" Contract Strategy',
        file="04-contract-strategy.docx",
        # Curly quotes, where the author's own file has straight ones: Windows
        # browsers strip `"` out of a download name and leave underscores. These
        # survive every OS and read the same.
        download_name="An “Irreparably Flawed” Contract Strategy",
        summary=("The procurement strategy and risk transfer — the fixed-price "
                 "premise, the Wiesbaden deal and the pricing assumptions."),
        keywords=[
            "contract strategy", "commercial strategy", "procurement",
            "procurement strategy", "flawed", "irreparably flawed",
            "risk transfer", "transfer of risk", "risk allocation",
            "fixed price", "lump sum", "pricing", "price",
            "contract negotiation", "tendering", "tender",
            # the specifics that identify 04 and nothing else
            "wiesbaden", "side deal", "dla piper", "legal advice",
            "notified departure", "notified departures", "schedule part 4",
            "infraco contract", "bbs",
        ],
    ),
    ChronologyDoc(
        ref="05",
        title="Severe Contractor Disputes and Work Stoppages",
        file="05-contractor-disputes.docx",
        download_name="Severe Contractor Disputes and Work Stoppages",
        summary=("The breakdown between tie and BSC — the Dispute Resolution "
                 "Procedure, the adjudications, mediation and the stoppages."),
        keywords=[
            "dispute", "disputes", "disputed", "contractor disputes",
            "breakdown", "standstill", "stoppage", "stoppages",
            "work stoppages", "downing tools", "suspension", "suspended",
            "dispute resolution procedure", "adjudication", "adjudications",
            "mediation", "litigation", "arbitration", "claims",
            # where it happened, and who with
            "princes street", "bsc", "bilfinger", "siemens", "caf",
            "infraco", "consortium",
        ],
    ),
    ChronologyDoc(
        ref="06",
        title="Withdrawal of National Oversight",
        file="06-national-oversight.docx",
        download_name="Withdrawal of National Oversight",
        summary=("Transport Scotland stepping back to a funding-only role, "
                 "and the monitoring that went with it."),
        keywords=[
            "oversight", "national oversight", "withdrawal", "withdrew",
            "stepped back", "hands off", "monitoring", "scrutiny",
            # the bodies that only 06 is about
            "transport scotland", "scottish government", "scottish ministers",
            "ministers", "government", "central government", "cabinet",
            "funding", "funder", "funded", "funds", "grant", "grant offer",
            "partnerships uk",
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
# Words that carry no subject signal. Interrogatives matter as much as
# articles here: the score is a mean over query words, so "who funded it"
# without them is two tokens where only one can match, and a perfect hit on
# "funded" averages down to 0.5 and falls under the threshold.
_STOP = {
    # articles, prepositions, copulas
    "the", "a", "an", "of", "and", "or", "for", "to", "in", "on", "at", "by",
    "with", "about", "is", "was", "were", "are", "be", "been", "that", "this",
    "it", "its", "their", "there",
    # interrogatives and the verbs that carry them
    "who", "what", "when", "where", "why", "how", "which", "whose",
    "did", "does", "do", "had", "has", "have",
    # what people say when they mean "show me the chronology"
    "chronology", "chronologies", "history", "timeline", "sequence", "events",
    "show", "me", "my", "give", "tell", "about", "happened", "story",
    "report", "explain", "describe",
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



def _shared_prefix(a: str, b: str) -> int:
    """Length of the common leading run of two words."""
    n = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        n += 1
    return n


def _term_score(query_token: str, terms: List[tuple]) -> float:
    """Best match for one query word: exact, shared stem, then substring."""
    best = 0.0
    for word, weight in terms:
        if word == query_token:
            s = weight
        elif len(query_token) >= 4 and (word.startswith(query_token) or query_token.startswith(word)):
            # "utilities" ~ "utility", "disputes" ~ "dispute"
            s = weight * 0.75
        elif _shared_prefix(query_token, word) >= 5:
            # A shared root the prefix test above cannot see, because the words
            # diverge after it: "diverted" ~ "diversion" (5), "governed" ~
            # "governance" (6). Five is safe rather than lax — "contract" and
            # "contractor" share eight and are already caught above, while
            # genuinely unrelated pairs like "dispute" and "disruption" share
            # only three and stay apart.
            s = weight * 0.7
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



# "On 29 March 2005, tie issued…" / "In March 2007, the parties…" / "By May
# 2007, …" — the authored entries lead with when it happened, so the date is
# pulled out to be set against the paragraph rather than buried in it. Entries
# that open with context instead of a date keep their sentence whole.
#
# The first version took only a bare date after a small set of prepositions, and
# measured against the real files it left 16 of 22 undated entries showing "—"
# in the date column while their own first words gave the period:
#
#   "By late 2008, after the Infraco Contract was let…"    → qualifier
#   "In 2010–2011, tie issued a Remediable Termination…"   → year range
#   "In June–July 2010, tie pursued an RTN strategy…"      → month range
#   "In December 2008 and January 2009, the TPB…"          → paired months
#   "From late 2009, tie's management of the Infraco…"     → qualifier
#   "Between June and December 2010, the Project…"         → unlisted preposition
#
# A chronology that prints "—" against a paragraph beginning "By late 2008" is
# hiding a date it was handed, so the pattern now covers qualifiers, ranges and
# pairs. The trailing comma is kept as the structural signal: without it, a
# sentence merely *containing* a year would be mistaken for a dated entry.
_MONTH = ("January|February|March|April|May|June|July|August|September|"
          "October|November|December")
# One point in time: "29 March 2005", "March 2007", "2007" — and a day range
# inside a single month, "28–30 April 2008", which the authored files use for
# meetings that ran over consecutive days.
_DAY = r"\d{1,2}(?:st|nd|rd|th)?"
_ATOM = (rf"(?:{_DAY}(?:\s*[–—-]\s*{_DAY})?\s+)?(?:{_MONTH})(?:\s+\d{{4}})?"
         rf"|\d{{4}}")
# "late 2008", "early 2007", "mid-2009", "the end of 2010".
_QUAL = (r"(?:(?:late|early|mid)[-\s]+|"
         r"the\s+(?:end|start|beginning)\s+of\s+)")
_POINT = rf"(?:{_QUAL})?(?:{_ATOM})"
# "2010–2011", "June–July 2010", "December 2008 and January 2009".
_JOIN = r"\s*(?:–|—|-|to|and|through|until)\s*"
_DATE_PHRASE = rf"{_POINT}(?:{_JOIN}{_POINT})?"

# "On 29 March 2005" reads better in a date column as "29 March 2005" — the
# preposition is grammar. "By late 2008" and "Between June and December 2010" do
# not: drop the word and the column claims a point in time where the source
# gave a boundary or a span. So point markers are dropped and span markers kept.
_POINT_PREP = "On|In|At"
_SPAN_PREP = ("By|From|During|Between|Throughout|Over|Since|Until|"
              "Following|After|Before|Around")

_DATE_LEAD_RE = re.compile(
    rf"^(?:(?:{_POINT_PREP})|(?P<span>{_SPAN_PREP}))\s+"
    rf"(?P<date>{_DATE_PHRASE})\s*,\s*(?P<rest>.+)$",
    re.I,
)


def _split_date(text: str) -> tuple:
    """(date, remaining sentence) — ("", text) when it does not open with one."""
    m = _DATE_LEAD_RE.match(text)
    if not m:
        return "", text
    when = m.group("date").strip()
    span = m.group("span")
    if span:
        when = f"{span} {when}"
    rest = m.group("rest").strip()
    # Left as written. Recapitalising the first word looks tidier until it hits
    # "tie" — the delivery company's name is lowercase by design throughout
    # these documents, and "Tie issued…" is simply wrong. The date sits in its
    # own column anyway, so the sentence reads fine starting mid-clause.
    return when, rest or text


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
            body = m.group(2).strip()
            when, body = _split_date(body)
            entries.append({"ref": m.group(1), "date": when, "text": body, "sub": []})
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


def doc_path(doc: ChronologyDoc) -> Path:
    """Where the authored .docx actually sits."""
    return CHRONOLOGY_DIR / doc.file


def download_filename(doc: ChronologyDoc) -> str:
    """The name a download of this chronology should arrive under."""
    stem = (doc.download_name or doc.title or Path(doc.file).stem).strip()
    return stem + Path(doc.file).suffix
