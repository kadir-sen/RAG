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

from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel

from backend.core.security import get_current_user, UserContext
from backend.core.projects import ProjectContext, get_current_project

router = APIRouter()

# How much of the store we are willing to READ before scoping. This is a memory
# backstop, not a business rule — it exists only so a runaway store cannot pull
# the 2 GB box over. Counting and exporting must see the whole record, and
# reading through the page limit is what made them lie: /summary and /facets
# fetched 500 rows, scoped those, and reported the result as the total. With
# more than 500 delay events alone in the store, the page confidently said
# "499 events on file" and drew a chip reading "delay · 1".
_READ_CEILING = 100_000

# The export has no row ceiling of its own. There was one, and it was the wrong
# shape: a document that stops at a round number and tells the reader to narrow
# their filters is refusing to hand over the record while sounding helpful about
# it. What made "whole" affordable was the layout — indented paragraphs instead
# of a Word table — which builds ~28k events in seconds rather than minutes.
# _READ_CEILING above is the only bound left, and it is a memory backstop set far
# above the real store, not a product rule.


def _scoped_rows(user: UserContext, project_id: str = "", **filters) -> List[Dict]:
    """Every event this user can see under these filters, unpaged.

    Callers that page apply their own limit afterwards. Reading the full set
    first is the point: the corpus scoping drops rows, so truncating before it
    lets another corpus's events eat the window and makes any count downstream
    an undercount of unknown size.
    """
    from src.event_timeline import get_event_timeline

    rows = get_event_timeline().timeline_context(
        limit=_READ_CEILING, project=project_id or None, **filters,
    )
    if len(rows) >= _READ_CEILING:
        # Never expected — the ceiling sits far above the store — but if it ever
        # bites, every count and every export below it is quietly short, so say
        # so somewhere rather than let it pass as a total.
        from src.logger import logger
        logger.warning(
            f"[Chronology] read ceiling {_READ_CEILING} reached — counts and "
            f"exports are truncated. Raise _READ_CEILING or page the store."
        )
    if project_id:
        return rows
    return _scope_to_corpus(rows, user)


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
async def chronology_summary(
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(get_current_project),
) -> Dict[str, int]:
    """How many events this user can see. Drives the header count and, when
    zero, the empty state that explains the corpus has not been enriched yet.

    Counted through the same corpus scoping as /events rather than the store's
    raw count(), so the header can never promise rows the list won't show — but
    over the whole store, not the first page of it.
    """
    return {"total_events": len(_scoped_rows(user, project.project_id))}


@router.get("/chronology/facets")
async def chronology_facets(
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(get_current_project),
) -> Dict[str, Dict[str, int]]:
    """Event counts per type, for the filter chips.

    Counted over the corpus-scoped rows, not the store's type_counts(), for the
    same reason as /summary: a chip showing 12 that filters down to nothing is
    worse than no chip. Types with no visible events are omitted rather than
    sent as zeros.
    """
    from collections import Counter

    counts = Counter(r.get("event_type") for r in _scoped_rows(user, project.project_id)
                     if r.get("event_type"))
    return {"event_type": dict(counts)}


@router.get("/chronology/events")
async def chronology_events(
    event_type: Optional[str] = Query(None, description="delay|disruption|excuse|decision|milestone|claim"),
    actor: Optional[str] = Query(None, description="substring match on the acting party"),
    date_from: Optional[str] = Query(None, description="ISO date, inclusive"),
    date_to: Optional[str] = Query(None, description="ISO date, inclusive"),
    # No product ceiling: the list starts at a screenful and the caller walks it
    # to the end of the record. The bound is the same memory backstop the reads
    # use, so nothing here refuses a page the store could actually serve.
    limit: int = Query(200, ge=1, le=_READ_CEILING),
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(get_current_project),
) -> Dict[str, Any]:
    """Events oldest-first, filtered.

    timeline_context is the right primitive rather than timeline(): it carries
    doc_id, which is what makes a row clickable through to the viewer, and it
    is the one that understands a date range.

    The store is asked for the full window and the corpus scoping is applied
    after, then the caller's limit — filtering first would let another corpus's
    rows eat the limit and return a short page for no visible reason.

    `matching` is how many events the filters actually select; `events` is the
    page of them this response carries. They differ, often by a lot, and the
    header needs the first number to avoid describing a page as a record.
    """
    rows = _scoped_rows(
        user, project.project_id, event_type=event_type, actor=actor,
        date_from=date_from, date_to=date_to,
    )
    return {"events": rows[:limit], "matching": len(rows)}


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

# The three response headers live in backend/api/_docx.py now — the chat-answer
# export needs exactly the same set, and a second copy of
# Access-Control-Expose-Headers is the kind of omission that only shows up in a
# browser, as a file called "download".
from ._docx import docx_response as _docx_response  # noqa: E402


@router.get("/chronology/subjects/{ref}/document")
async def chronology_subject_docx(
    ref: str,
    rendered: bool = Query(False),
    user: UserContext = Depends(get_current_user),
) -> Response:
    """One authored chronology as a Word document.

    By default this is the authored file itself, byte for byte, under the name
    its author gave it. What comes down is pasted straight into a report, and a
    re-typeset copy — same words, our layout, our stamp — is not the document
    anyone was handed. `?rendered=1` returns that copy, with the evidence
    section, for the cases that want it.
    """
    from fastapi import HTTPException

    from src.chronology_library import doc_path, download_filename, get_doc

    doc = get_doc(ref)
    if doc is None:
        raise HTTPException(status_code=404, detail="No such chronology")

    if not rendered:
        path = doc_path(doc)
        if not path.is_file():
            # The ref is good; the deployment is not. Say so rather than 404 —
            # and do not quietly fall back to the rendered build, which reads
            # the same missing file and would hand over an empty chronology
            # that looks like the real one.
            from src.logger import logger
            logger.error(f"[Chronology] authored file missing: {path}")
            raise HTTPException(status_code=500,
                                detail="Chronology file missing on this deployment")
        return _docx_response(path.read_bytes(), download_filename(doc))

    from src.chronology_docx import build_subject_docx, safe_filename
    from src.chronology_library import COLLECTION, get_entries

    # If an evidence pass has already run for this subject, the export carries it.
    # The narrative names no source files, so a chronology handed on without them
    # asserts a history with nothing to check it against.
    from src.chronology_evidence import cached as cached_evidence
    blob = build_subject_docx(_doc_out(doc), get_entries(ref), COLLECTION,
                              evidence=cached_evidence(ref, _corpus_of(user)))
    return _docx_response(blob, safe_filename("Chronology", doc.ref, doc.title) + ".docx")


@router.get("/chronology/events/document")
async def chronology_events_docx(
    event_type: Optional[str] = Query(None),
    actor: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(get_current_project),
) -> Response:
    """The event list as a Word document, under the same filters and the same
    corpus scoping as /chronology/events — an export that could show rows the
    page cannot would be worse than no export.

    Unpaged and uncapped: someone asking for a document wants the record.
    """
    from src.chronology_docx import build_events_docx, safe_filename

    rows = _scoped_rows(
        user, project.project_id, event_type=event_type, actor=actor,
        date_from=date_from, date_to=date_to,
    )
    blob = build_events_docx(rows, {
        "event_type": event_type, "actor": actor,
        "date_from": date_from, "date_to": date_to,
    })
    return _docx_response(blob, safe_filename("Chronology", "project-record") + ".docx")


# ── the staged, evidence-backed build ───────────────────────────────────
# Typing a subject used to return in milliseconds: the match is token scoring and
# the narrative is parsed from a cached .docx, so the "Finding…" state was never
# actually seen and the report arrived looking like a canned lookup. It also had
# no link to the corpus at all — 80 entries across the six chronologies and not
# one naming a source file — so "which document is 6.3.4 about?" had no answer.
#
# This endpoint answers it. The wait is filled by resolving that evidence, not by
# sleeping: BM25 over the mirrored chunk text for the subject and then for every
# entry and sub-point, plus the extracted events falling in each dated entry's
# period. The payload reports elapsed_ms, passes and how much corpus was searched
# so the page can print what actually happened.
#
# /chronology/match is left alone. It is a cheap honest resolver used by the
# ambiguity path and the candidate chips, and making it sometimes-slow would
# change its contract for callers that only want a name.


class BuildRequest(BaseModel):
    subject: str = ""
    ref: str = ""
    # Client-generated, so the page can poll GET /chat/progress/{request_id} for
    # the live steps. That store is keyed on request_id alone and knows nothing
    # about chat, so reusing it costs nothing and — the actual reason — the
    # retrieval already publishes its own "reading <file> · p.N" lines. A step
    # list written on the client could not name the document, and naming the
    # document is the whole point of this feature.
    request_id: str = ""
    force: bool = False


@router.post("/chronology/build")
async def chronology_build(
    body: BuildRequest, user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(get_current_project),
) -> Dict:
    """Resolve one authored chronology together with its corpus evidence."""
    import asyncio
    import uuid

    from src.chronology_evidence import build as build_evidence, has_corpus
    from src.chronology_library import get_doc, get_entries, match
    from backend.tasks.query_progress import (query_progress, query_request_var,
                                              report_step)

    # Cheap path first: there is nothing to build until we know which chronology.
    if body.ref:
        doc = get_doc(body.ref)
        if doc is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="No such chronology")
    else:
        result = match(body.subject or "")
        if result["status"] != "match":
            return {"status": result["status"],
                    "candidates": [_doc_out(r["doc"]) for r in result["ranked"]]}
        doc = result["doc"]

    entries = get_entries(doc.ref)
    payload = {"status": "match", "subject": _doc_out(doc), "entries": entries}

    # No corpus to search: return at once and say why. A staged build in front of
    # an empty evidence section would be the exact misrepresentation this is
    # meant to avoid.
    if not has_corpus():
        return {**payload, "evidence": None,
                "evidence_note": "No searchable corpus for this account, so there "
                                 "is no supporting evidence to resolve."}

    request_id = body.request_id or uuid.uuid4().hex[:12]
    corpus = project.project_id

    def _run() -> Dict:
        # The ContextVar rides into this thread via to_thread, which is also what
        # lets document_rag/lexical publish their own steps under the same id.
        query_request_var.set(request_id)
        from src.project_context import set_current_project
        from backend.core.security import set_current_user_context
        set_current_user_context(user.username)
        set_current_project(project.project_id, project.role)
        return build_evidence(
            doc.ref, doc.title, doc.summary, entries,
            corpus=corpus,
            corpus_filter=lambda rows: [r for r in rows
                                        if (r.get("project") or project.project_id) == project.project_id],
            force=body.force,
            on_step=report_step,
        )

    query_progress.start(request_id)
    try:
        # to_thread is not optional here. These handlers are async but the work is
        # synchronous DuckDB and python-docx; at milliseconds nobody noticed, but a
        # multi-second build on the event loop would stall every other request on
        # a 2 vCPU box.
        evidence = await asyncio.to_thread(_run)
    finally:
        query_progress.finish(request_id)

    return {**payload, "evidence": evidence, "request_id": request_id}
