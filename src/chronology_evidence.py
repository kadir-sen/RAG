"""Which corpus documents stand behind an authored chronology.

The six authored chronologies are narrative. 80 numbered entries across them, 71
carrying a date, and **not one naming a source file** — checked, zero
filename-shaped matches in any entry or sub-point. So "which of the 7,289
documents in the corpus is entry 6.3.4 actually about?" has no answer today, in
the page or in the export. This module answers it, deterministically:

  * BM25 over the mirrored chunk text (src/lexical_index) — for the subject as a
    whole, then for each entry and sub-point on its own;
  * the extracted event store (src/event_timeline) — the events falling in each
    dated entry's period.

**No model anywhere.** That is not decoration: the chronology area tells the
reader it never goes near an LLM, and this is the first thing in that area to
touch the corpus, so it has to keep the promise. The lexical lane is local by
construction; the subject-level pass would need one embedding, so it uses the
same lexical lane rather than making an offline-deterministic feature depend on
an external API.

WHAT THIS COSTS, MEASURED. Chronology 03, 14 entries, dev machine: about 2
seconds. It is **not** a 20-second job and nothing here pretends it is. When a
caller wants a longer window it gets it by asking for MORE evidence — `deepen`
widens the search and takes in the sub-points — never by sleeping. `elapsed_ms`,
`passes` and `units_searched` come back in the payload so the page can print what
actually happened rather than a number someone chose.
"""

from __future__ import annotations

import calendar
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .logger import logger

# What a deepened build aims at. A target, not a promise — when the corpus is
# small or the entries are short the work finishes early and the payload says so.
#
# Measured on the production box (2 vCPU, warm index): a 13 s budget produced a
# 14.9 s round trip covering 7 of 21 units. 17 s lands the round trip near 19 s —
# the middle of the window the owner asked for — and buys a couple more entries.
# Full coverage of all 21 would need roughly 40 s there, which is worse than
# partial coverage that says so: `budget_exhausted` is reported and the page
# prints "budget reached, later entries not searched".
BUDGET_MS = 17_000

SUBJECT_TOP_K = 24
ENTRY_TOP_K = 5
DEEPEN_TOP_K = 12
EVENT_LIMIT = 10
# An event a month either side of a dated entry is still that entry's event. The
# padding is reported rather than left as a magic number: a reader who sees an
# event listed under "28 March 2006" is entitled to know the window it came from.
EVENT_PAD_DAYS = 30
MAX_DOCUMENTS = 40

# How long a resolved evidence set may be reused.
#
# Short by design. A reused result comes back in under a tenth of a second, and
# a report that appears instantly does not read as one that was resolved on the
# spot — it reads as one that was prepared earlier. That impression is wrong:
# the search really does run over 7,289 documents every time it is not reused.
# But the timing is what a reader believes, so the window in which anyone can
# see the fast path is kept to a minute, which is enough to cover a double-click
# or a reload and nothing more.
#
# 0 disables reuse entirely. Raise it when nobody is watching the clock and the
# repeat work is the thing worth avoiding.
CACHE_TTL_S = int(os.getenv("CHRONOLOGY_EVIDENCE_CACHE_TTL_S", "60"))

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_YEAR = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
_DAY = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\b")


# ── the date window ─────────────────────────────────────────────────────
def entry_window(date_text: str) -> Optional[Tuple[str, str]]:
    """(from, to) ISO dates covering the period an entry names, or None.

    Deliberately not built on event_timeline._date_sort_key. That is a sort key,
    not a range, and it takes the first month it finds by dictionary order rather
    than by position in the text — so "December 2008 and January 2009" sorts as
    April. Here the *span* is what matters, so both ends are read.
    """
    text = (date_text or "").strip().lower()
    if not text:
        return None

    years = [int(y) for y in _YEAR.findall(text)]
    if not years:
        return None

    # Months are paired with the year that FOLLOWS them in the text, not
    # min/maxed globally. "December 2008 and January 2009" has months {1, 12} and
    # years {2008, 2009}: taking the extremes of each independently gives
    # January 2008 → December 2009, two years instead of two months. Reading them
    # in order gives December 2008 → January 2009, which is what it says.
    tokens = re.findall(r"[a-z]+|\d+", text)
    pairs: List[Tuple[int, int]] = []           # (year, month)
    pending: List[int] = []
    for tok in tokens:
        if tok in _MONTHS:
            pending.append(_MONTHS[tok])
        elif tok.isdigit() and len(tok) == 4:
            year = int(tok)
            for m in pending or []:
                pairs.append((year, m))
            pending = []
    # A trailing month with no year after it belongs to the last year seen.
    if pending and years:
        for m in pending:
            pairs.append((years[-1], m))

    days = [int(d) for d in _DAY.findall(re.sub(r"\b(1[89]\d{2}|20\d{2})\b", " ", text))]

    if not pairs:
        # "1905", "2010–2011", "By late 2008" → whole years.
        return f"{min(years)}-01-01", f"{max(years)}-12-31"

    (y0, m0), (y1, m1) = min(pairs), max(pairs)
    single = len(pairs) == 1
    last = calendar.monthrange(y1, m1)[1]
    start_day = min(days) if days and single else 1
    end_day = max(days) if days and single else last
    first_last = calendar.monthrange(y0, m0)[1]
    return (f"{y0}-{m0:02d}-{min(start_day, first_last):02d}",
            f"{y1}-{m1:02d}-{min(end_day, last):02d}")


def _pad(window: Tuple[str, str], days: int = EVENT_PAD_DAYS) -> Tuple[str, str]:
    def shift(iso: str, delta: int) -> str:
        y, m, d = (int(p) for p in iso.split("-"))
        return (date(y, m, d) + timedelta(days=delta)).isoformat()
    try:
        return shift(window[0], -days), shift(window[1], days)
    except Exception:
        return window


# ── one resolved unit of the narrative ──────────────────────────────────
@dataclass
class Unit:
    ref: str
    kind: str                      # "entry" | "sub"
    date: str = ""
    documents: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    window: Optional[List[str]] = None


def _search(query: str, top_k: int) -> List[Dict[str, Any]]:
    """BM25 over the mirrored chunk text. Never raises — a build that loses one
    pass is worth more than a build that dies."""
    try:
        from .lexical_index import get_lexical_index
        from .project_context import get_current_project_id
        return get_lexical_index().search_chunks(
            query, top_k=top_k, project_id=get_current_project_id() or None,
        ) or []
    except Exception as exc:
        logger.warning(f"[ChronEvidence] lexical pass failed: {exc}")
        return []


def _as_document(hit: Dict[str, Any]) -> Dict[str, Any]:
    """A chunk hit → the shape the page and the export want.

    doc_id is the *file name* on purpose: these documents have no registry entry,
    and the viewer resolves them by name (see the file_name fallback in
    backend/services/document_service). A path-derived hash would 404.
    """
    file_name = str(hit.get("file_name") or "")
    page = hit.get("page_number") or 1
    return {
        "doc_id": file_name,
        "file_name": file_name,
        "page_number": int(page or 1),
        "anchor": f"page_{int(page or 1)}",
        "snippet": (str(hit.get("text") or "").strip()[:280]),
        "score": round(float(hit.get("lex_score") or 0.0), 4),
    }


def _events_for(window: Tuple[str, str], corpus_filter) -> List[Dict[str, Any]]:
    try:
        from .event_timeline import get_event_timeline
        lo, hi = _pad(window)
        from .project_context import get_current_project_id
        rows = get_event_timeline().timeline_context(
            date_from=lo, date_to=hi, project=get_current_project_id() or None,
            limit=EVENT_LIMIT * 4) or []
    except Exception as exc:
        logger.warning(f"[ChronEvidence] event pass failed: {exc}")
        return []
    if corpus_filter is not None:
        rows = corpus_filter(rows)
    return [{"date": r.get("date", ""), "event_type": r.get("event_type", ""),
             "actor": r.get("actor", ""), "file_name": r.get("file_name", ""),
             "description": (r.get("description") or r.get("reason") or "")[:240]}
            for r in rows[:EVENT_LIMIT]]


# ── cache ───────────────────────────────────────────────────────────────
_cache: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


def cached(ref: str, corpus: str) -> Optional[Dict[str, Any]]:
    if CACHE_TTL_S <= 0:          # reuse switched off entirely
        return None
    with _lock:
        hit = _cache.get(f"{ref}|{corpus}")
    if not hit:
        return None
    if time.time() - hit["built_at"] > CACHE_TTL_S:
        return None
    return hit


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def build(
    ref: str,
    title: str,
    summary: str,
    entries: List[Dict[str, Any]],
    *,
    corpus: str = "",
    corpus_filter=None,
    deepen: bool = True,
    budget_ms: int = BUDGET_MS,
    force: bool = False,
    on_step=None,
) -> Dict[str, Any]:
    """Resolve the corpus evidence behind one authored chronology.

    `on_step(kind, label, detail)` is called as the work happens, so the caller
    can publish it to a live feed. Every label describes an operation that
    actually ran — no step is emitted for work that did not happen.
    """
    if not force:
        hit = cached(ref, corpus)
        if hit:
            if on_step:
                age = int(time.time() - hit["built_at"])
                on_step("searching", "evidence already resolved",
                        f"reusing · built {age}s ago")
            return {**hit, "from_cache": True}

    # Warm the search index BEFORE the clock starts. DuckDB builds its full-text
    # index on first use and that took 19 seconds on this corpus — enough to eat
    # the entire budget on the first build of a process, so every entry pass was
    # skipped and the payload reported one pass and zero units. It is a one-off
    # cost that belongs to the process, not to this chronology, and the reader is
    # told it is happening rather than left watching a stall.
    if on_step:
        on_step("thinking", "preparing the search index")
    _warm_index()

    started = time.monotonic()
    passes = 0
    units: List[Unit] = []
    by_name: Dict[str, Dict[str, Any]] = {}

    def note(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for h in hits:
            doc = _as_document(h)
            if not doc["file_name"]:
                continue
            out.append(doc)
            keep = by_name.get(doc["file_name"])
            if keep is None or doc["score"] > keep["score"]:
                by_name[doc["file_name"]] = doc
        return out

    # 1) The subject as a whole — the broad base.
    if on_step:
        on_step("searching", "searching the corpus", f"{title}"[:80])
    subject_hits = note(_search(f"{title} {summary}", SUBJECT_TOP_K))
    passes += 1
    if on_step and subject_hits:
        on_step("reading", f"{len(by_name)} document(s) match the subject",
                subject_hits[0]["file_name"])

    # 2) Each entry on its own, then — if there is budget — its sub-points.
    #    Entries first so a tight budget still covers every entry.
    plan: List[Tuple[str, str, str, str]] = [
        (e.get("ref", ""), "entry", e.get("text", ""), e.get("date", ""))
        for e in entries
    ]
    if deepen:
        plan += [(e.get("ref", ""), "sub", s, e.get("date", ""))
                 for e in entries for s in (e.get("sub") or [])]

    exhausted = False
    for ref_i, kind, text, date_text in plan:
        if (time.monotonic() - started) * 1000 > budget_ms:
            exhausted = True
            break
        if not (text or "").strip():
            continue
        top_k = DEEPEN_TOP_K if kind == "entry" else ENTRY_TOP_K
        hits = note(_search(text, top_k))
        passes += 1
        unit = Unit(ref=ref_i, kind=kind, date=date_text, documents=hits[:6])
        window = entry_window(date_text)
        if window:
            unit.window = list(_pad(window))
            unit.events = _events_for(window, corpus_filter)
        units.append(unit)
        if on_step:
            detail = hits[0]["file_name"] if hits else "no match"
            on_step("reading", f"{ref_i} · {len(hits)} document(s)", detail)

    documents = sorted(by_name.values(), key=lambda d: -d["score"])[:MAX_DOCUMENTS]
    elapsed_ms = int((time.monotonic() - started) * 1000)
    dated = sum(1 for u in units if u.window)
    with_events = sum(1 for u in units if u.events)

    result = {
        "ref": ref,
        "documents": documents,
        "units": [asdict(u) for u in units],
        "passes": passes,
        "units_searched": len(units),
        "dated_units": dated,
        "units_with_events": with_events,
        "elapsed_ms": elapsed_ms,
        "budget_exhausted": exhausted,
        "event_pad_days": EVENT_PAD_DAYS,
        "corpus_searched": _corpus_size(),
        "built_at": time.time(),
        "from_cache": False,
    }
    with _lock:
        _cache[f"{ref}|{corpus}"] = result
    logger.info(
        f"[ChronEvidence] {ref}: {len(documents)} documents, {len(units)} units, "
        f"{passes} passes, {with_events}/{dated} dated units with events, "
        f"{elapsed_ms}ms{' (budget reached)' if exhausted else ''}"
    )
    if on_step:
        on_step("analysing", f"{len(documents)} document(s) resolved",
                f"{passes} passes · {elapsed_ms} ms")
    return result


def _warm_index() -> None:
    """Force the one-off full-text index build, outside the budget clock."""
    try:
        _search("warm", 1)
    except Exception:
        pass


def _corpus_size() -> int:
    """How many documents were searchable. Printed on the page, so it is read
    rather than assumed."""
    try:
        from .chunk_store import get_chunk_store
        con = get_chunk_store().connection()
        return int(con.execute(
            "SELECT COUNT(DISTINCT file_name) FROM chunks "
            "WHERE file_name IS NOT NULL AND file_name <> ''").fetchone()[0])
    except Exception:
        return 0


def has_corpus() -> bool:
    """Whether there is anything to search at all.

    A staged build in front of an empty evidence section would be theatre, so the
    caller checks this first and returns immediately when it is false.
    """
    return _corpus_size() > 0
