"""Chronology endpoints — the event timeline as its own area.

The event store has been in the tree for a while but had no HTTP surface: the
only reader was the router's timeline handler, which answered chronology
*questions* inside the chat. That handler is gone: chronology is a place you
go rather than a question you ask, so it is read directly — filtered, faceted and
paged, with no LLM in the path.

src/event_timeline.py already exposes exactly the right primitives
(timeline_context / type_counts / count), all deterministic DuckDB reads, so
this module is a thin, honest wrapper over them.
"""

from typing import Dict, List, Optional, Set

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel

from backend.core.security import get_current_user, UserContext

router = APIRouter()

# Whatever the caller asks for, never return more than this in one response.
# The store's own default is 60; the area pages rather than scrolls forever.
_MAX_LIMIT = 500


def _corpus_of(user: UserContext) -> str:
    """Which corpus this user sees. Mirrors backend/api/library.py so the two
    do not drift — same features dict, same lowercasing, same empty default."""
    try:
        return str((user.features or {}).get("corpus") or "").lower()
    except Exception:
        return ""


def _registry_file_names() -> Set[str]:
    """File names of completed registry documents — i.e. the demo corpus.

    This is the same split /library draws: demo documents have registry
    entries, the bulk (edinburgh) ones were ingested vectors-only and do not.
    """
    from src.document_registry import get_document_registry

    return {r.file_name for r in get_document_registry().get_completed()}


def _scope_to_corpus(rows: List[Dict], user: UserContext) -> List[Dict]:
    """Keep only the events whose source document this user can see.

    The event rows carry no corpus column — ingest writes project="" — so the
    corpus has to be inferred from the source file, and the registry membership
    test is the same one /library uses.

    router.py:3302 does this differently and, on the current data, wrongly: it
    drops every event for demo users on the stated grounds that "the event store
    is extracted from the bulk (edinburgh) corpus". The store's contents say
    otherwise — all of it came from demo-corpus .msg files under data/emails/ —
    so that gate hides the events from the only account entitled to them.
    Deriving the answer from the data instead of asserting it means this cannot
    silently invert again when the corpora shift.

    Still worth a `corpus` column on the events table eventually; then this
    becomes a WHERE clause and the join goes away.
    """
    known = _registry_file_names()
    if _corpus_of(user) == "edinburgh":
        return [r for r in rows if r.get("file_name") not in known]
    return [r for r in rows if r.get("file_name") in known]


@router.get("/chronology/summary")
async def chronology_summary(user: UserContext = Depends(get_current_user)) -> Dict[str, int]:
    """How many events this user can see. Drives the header count and, when
    zero, the empty state that explains the corpus has not been enriched yet.

    Counted through the same corpus scoping as /events rather than the store's
    raw count(), so the header can never promise rows the list won't show.
    """
    from src.event_timeline import get_event_timeline

    rows = get_event_timeline().timeline_context(limit=_MAX_LIMIT)
    return {"total_events": len(_scope_to_corpus(rows, user))}


@router.get("/chronology/facets")
async def chronology_facets(user: UserContext = Depends(get_current_user)) -> Dict[str, Dict[str, int]]:
    """Event counts per type, for the filter chips.

    Counted over the corpus-scoped rows, not the store's type_counts(), for the
    same reason as /summary: a chip showing 12 that filters down to nothing is
    worse than no chip. Types with no visible events are omitted rather than
    sent as zeros.
    """
    from collections import Counter

    from src.event_timeline import get_event_timeline

    rows = _scope_to_corpus(get_event_timeline().timeline_context(limit=_MAX_LIMIT), user)
    counts = Counter(r.get("event_type") for r in rows if r.get("event_type"))
    return {"event_type": dict(counts)}


@router.get("/chronology/events")
async def chronology_events(
    event_type: Optional[str] = Query(None, description="delay|disruption|excuse|decision|milestone|claim"),
    actor: Optional[str] = Query(None, description="substring match on the acting party"),
    date_from: Optional[str] = Query(None, description="ISO date, inclusive"),
    date_to: Optional[str] = Query(None, description="ISO date, inclusive"),
    limit: int = Query(200, ge=1, le=_MAX_LIMIT),
    user: UserContext = Depends(get_current_user),
) -> Dict[str, List[Dict]]:
    """Events oldest-first, filtered.

    timeline_context is the right primitive rather than timeline(): it carries
    doc_id, which is what makes a row clickable through to the viewer, and it
    is the one that understands a date range.

    The store is asked for the full window and the corpus scoping is applied
    after, then the caller's limit — filtering first would let another corpus's
    rows eat the limit and return a short page for no visible reason.
    """
    from src.event_timeline import get_event_timeline

    rows = get_event_timeline().timeline_context(
        event_type=event_type,
        actor=actor,
        date_from=date_from,
        date_to=date_to,
        limit=_MAX_LIMIT,
    )
    return {"events": _scope_to_corpus(rows, user)[:limit]}


# ── the authored chronologies ───────────────────────────────────────────
# A second, separate thing from the event store above. The store is extracted
# from the corpus and is browsed with filters; these are written narratives of
# a known issue, resolved by typing its subject. Both belong to the chronology
# area, and neither goes near an LLM.


class SubjectRequest(BaseModel):
    subject: str


def _doc_out(doc) -> Dict:
    return {"ref": doc.ref, "title": doc.title, "summary": doc.summary}


@router.get("/chronology/subjects")
async def chronology_subjects(_: UserContext = Depends(get_current_user)) -> Dict:
    """Every authored chronology — what the picker offers when a typed subject
    matches nothing, and what the area lists before anything is typed."""
    from src.chronology_library import COLLECTION, list_docs

    return {"collection": COLLECTION, "subjects": [_doc_out(d) for d in list_docs()]}


@router.post("/chronology/match")
async def chronology_match(
    body: SubjectRequest, _: UserContext = Depends(get_current_user),
) -> Dict:
    """Resolve a typed subject to one chronology and return its narrative.

    Token scoring with phrase bonuses, no LLM: the mapping from subject to
    document is fixed, and a model that occasionally picks the wrong
    chronology for a dispute is worse than one that asks. A close runner-up
    therefore returns "ambiguous" rather than a guess, and a weak best score
    returns "none" with the full list to choose from.
    """
    from src.chronology_library import get_entries, match

    result = match(body.subject or "")
    status = result["status"]

    if status == "match":
        doc = result["doc"]
        return {
            "status": "match",
            "subject": _doc_out(doc),
            "score": result["score"],
            "entries": get_entries(doc.ref),
        }

    return {
        "status": status,
        "candidates": [_doc_out(r["doc"]) for r in result["ranked"]],
    }


@router.get("/chronology/subjects/{ref}")
async def chronology_subject(
    ref: str, _: UserContext = Depends(get_current_user),
) -> Dict:
    """One chronology by reference — what a candidate chip resolves to when the
    typed subject was ambiguous or matched nothing."""
    from fastapi import HTTPException

    from src.chronology_library import get_doc, get_entries

    doc = get_doc(ref)
    if doc is None:
        raise HTTPException(status_code=404, detail="No such chronology")
    return {"status": "match", "subject": _doc_out(doc), "entries": get_entries(ref)}


# ── downloads ───────────────────────────────────────────────────────────
# A chronology is read and then handed on — to a solicitor, into a bundle, as an
# appendix. Copying it out of the browser loses the date column, which is the
# one thing that makes it a chronology, so both views export as .docx laid out
# the way the page lays them out.

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _docx_response(blob: bytes, filename: str) -> Response:
    return Response(
        content=blob,
        media_type=_DOCX_MIME,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # The browser fetches this with XHR to attach the bearer token, so
            # the header has to be readable from script to name the file.
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.get("/chronology/subjects/{ref}/document")
async def chronology_subject_docx(
    ref: str, _: UserContext = Depends(get_current_user),
) -> Response:
    """One authored chronology as a Word document."""
    from fastapi import HTTPException

    from src.chronology_docx import build_subject_docx, safe_filename
    from src.chronology_library import COLLECTION, get_doc, get_entries

    doc = get_doc(ref)
    if doc is None:
        raise HTTPException(status_code=404, detail="No such chronology")
    blob = build_subject_docx(_doc_out(doc), get_entries(ref), COLLECTION)
    return _docx_response(blob, safe_filename("Chronology", doc.ref, doc.title) + ".docx")


@router.get("/chronology/events/document")
async def chronology_events_docx(
    event_type: Optional[str] = Query(None),
    actor: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(_MAX_LIMIT, ge=1, le=_MAX_LIMIT),
    user: UserContext = Depends(get_current_user),
) -> Response:
    """The event list as a Word document, under the same filters and the same
    corpus scoping as /chronology/events — an export that could show rows the
    page cannot would be worse than no export.

    The default limit is the maximum rather than the page's 200: someone asking
    for a document wants the whole record, not the first screen of it.
    """
    from src.chronology_docx import build_events_docx, safe_filename
    from src.event_timeline import get_event_timeline

    rows = get_event_timeline().timeline_context(
        event_type=event_type, actor=actor,
        date_from=date_from, date_to=date_to, limit=_MAX_LIMIT,
    )
    rows = _scope_to_corpus(rows, user)[:limit]
    blob = build_events_docx(rows, {
        "event_type": event_type, "actor": actor,
        "date_from": date_from, "date_to": date_to,
    })
    return _docx_response(blob, safe_filename("Chronology", "project-record") + ".docx")
