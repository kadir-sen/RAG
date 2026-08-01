"""Library endpoints — global document registry."""

import os
import threading
from typing import List, Optional, Set

from fastapi import APIRouter, HTTPException, Depends

from backend.core.security import get_current_user, UserContext
from backend.core.projects import ProjectContext, get_current_project
from backend.models.responses import (
    LibraryClusterSummary,
    LibraryDocument,
    NoticeMetadataOut,
)

router = APIRouter()

# Cap how many vectors-only (chunk-store) documents we surface in the library.
# With a per-corpus split + a sidebar search box this can be generous; the
# frontend render-caps the visible rows.
_VECTORS_ONLY_LIMIT = int(os.getenv("LIBRARY_VECTORS_ONLY_LIMIT", "8000"))


def _corpus_of(user: UserContext) -> str:
    """Which document corpus this user sees. 'edinburgh' → the bulk vectors-only
    set; anything else → the registry (demo) documents. Keeps the two accounts'
    libraries separate without a full tenant model."""
    try:
        return str((user.features or {}).get("corpus") or "").lower()
    except Exception:
        return ""

_EMAIL_EXTS = {".eml", ".msg"}
_DATA_EXTS = {".xlsx", ".xls", ".csv"}


def _vectors_only_library_docs(known_names: Set[str], project_id: str = "",
                               limit: int = _VECTORS_ONLY_LIMIT) -> List[LibraryDocument]:
    """Documents that live only in the vector/chunk store (ingested without a
    registry entry — e.g. a bulk vectors-only corpus). They are NOT in the
    document registry, so the normal /library list misses them. We synthesise
    library entries straight from the chunk store's distinct file names. The
    viewer resolves them by file_name via its chunk-text fallback, so we set
    doc_id := file_name to make the click round-trip without a registry record.
    Read-only on the chunk store — no registry writes, safe under concurrency."""
    from src.chunk_store import get_chunk_store
    con = get_chunk_store().connection()
    sql = ("SELECT file_name FROM chunks WHERE file_name IS NOT NULL "
           "AND file_name <> ''")
    params = []
    if project_id:
        sql += " AND project_id = ?"
        params.append(project_id)
    rows = con.execute(sql + " GROUP BY file_name ORDER BY file_name", params).fetchall()
    out: List[LibraryDocument] = []
    for (file_name,) in rows:
        if file_name in known_names:
            continue
        ext = os.path.splitext(file_name)[1].lower()
        ftype = ("email" if ext in _EMAIL_EXTS
                 else "data" if ext in _DATA_EXTS else "document")
        out.append(LibraryDocument(
            doc_id=file_name,          # viewer chunk-text fallback matches file_name
            file_name=file_name,
            file_type=ftype,
            extension=ext,
            status="completed",
        ))
        if len(out) >= limit:
            break
    return out


def _catalog_corpus_by_name() -> dict:
    """file_name → catalog corpus tag, so listings can isolate per corpus."""
    try:
        from src.catalog import get_catalog
        return {os.path.basename(e.source_file): (getattr(e, "corpus", "demo") or "demo").lower()
                for e in get_catalog().entries.values()}
    except Exception:
        return {}


def _edinburgh_data_library_docs() -> List[LibraryDocument]:
    """LibraryDocument rows for the edinburgh corpus's SQL data tables (Excel/CSV)
    from the catalog — they're not in the chunk store, so the vectors-only library
    path misses them. doc_id == generate_doc_id(source_file) for viewer round-trip."""
    from src.catalog import get_catalog
    from src.document_rag import generate_doc_id
    out: List[LibraryDocument] = []
    for entry in get_catalog().entries.values():
        if (getattr(entry, "corpus", "demo") or "demo").lower() != "edinburgh":
            continue
        if entry.source_type not in ("excel", "csv"):
            continue
        fname = os.path.basename(entry.source_file)
        out.append(LibraryDocument(
            doc_id=generate_doc_id(entry.source_file),
            file_name=fname,
            file_type="data",
            extension=os.path.splitext(fname)[1].lower(),
            status="completed",
            table_names=[t.table_name for t in entry.tables],
        ))
    return out


def _load_notice_metadata(doc_id: str) -> Optional[NoticeMetadataOut]:
    """Load notice metadata from disk for a document."""
    try:
        from src.notice_extractor import get_notice_extractor
        extractor = get_notice_extractor()
        notice = extractor.load_notice(doc_id)
        if not notice:
            return None
        return NoticeMetadataOut(
            date=notice.date or "",
            sender=notice.sender or "",
            sender_company=getattr(notice, 'sender_company', "") or "",
            recipient=notice.recipient or "",
            subject=notice.subject or "",
            doc_type=notice.doc_type or "",
            direction=getattr(notice, 'direction', "") or "",
            ref_numbers=notice.ref_numbers or [],
            summary=getattr(notice, 'summary', "") or "",
        )
    except Exception:
        return None


def _build_library_doc(r, include_notice: bool = True) -> LibraryDocument:
    """Build LibraryDocument from a registry record."""
    notice = _load_notice_metadata(r.doc_id) if include_notice and r.notice_extracted else None
    return LibraryDocument(
        doc_id=r.doc_id,
        file_name=r.file_name,
        file_type=r.file_type,
        extension=r.extension,
        status=r.status,
        file_size_kb=r.file_size_kb,
        table_names=r.table_names,
        notice_extracted=r.notice_extracted,
        created_at=r.created_at,
        notice_metadata=notice,
        cluster_id=getattr(r, "cluster_id", None),
        cluster_label=getattr(r, "cluster_label", None),
    )


@router.get("/library", response_model=List[LibraryDocument])
async def list_library(
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(get_current_project),
):
    """List documents for the current user's corpus.

    'edinburgh' users see ONLY the bulk vectors-only documents; everyone else sees
    ONLY the registry (demo) documents. This keeps the admin (demo) and admin2
    (Edinburgh) libraries separate."""
    from src.document_registry import get_document_registry
    registry = get_document_registry()

    # All newly created projects use project_id as the authoritative boundary.
    # Legacy corpus tags remain below only for pre-project data migration.
    project_records = registry.get_completed(project_id=project.project_id)
    if project_records:
        return [_build_library_doc(r) for r in project_records]
    project_chunks = _vectors_only_library_docs(set(), project.project_id)
    if project_chunks:
        return project_chunks

    if _corpus_of(user) == "edinburgh":
        try:
            reg_names = {r.file_name for r in registry.get_completed()}
            docs = _vectors_only_library_docs(reg_names)
            docs.extend(_edinburgh_data_library_docs())  # Excel/CSV data tables
            return docs
        except Exception:
            return []
    # demo / default: registry documents only, minus any tagged to another corpus
    # (e.g. edinburgh data tables that were also registered) — no cross-corpus leak.
    corpus_by_name = _catalog_corpus_by_name()
    return [_build_library_doc(r) for r in registry.get_completed()
            if corpus_by_name.get(r.file_name, "demo") == "demo"]


@router.get("/library/summary")
async def library_summary(
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(get_current_project),
):
    """Document classification summary — count by doc_type and file_type, scoped to
    the current user's corpus (mirrors /library and /files)."""
    from src.document_registry import get_document_registry
    from collections import Counter

    registry = get_document_registry()
    completed_for_project = registry.get_completed(project_id=project.project_id)
    if completed_for_project:
        by_file_type = Counter(r.file_type for r in completed_for_project)
        return {
            "total_files": len(completed_for_project),
            "by_file_type": dict(by_file_type),
            "by_doc_type": {},
            "total_tables": sum(len(r.table_names) for r in completed_for_project),
        }
    project_chunk_docs = _vectors_only_library_docs(set(), project.project_id)
    if project_chunk_docs:
        by_file_type = Counter(d.file_type for d in project_chunk_docs)
        return {"total_files": len(project_chunk_docs), "by_file_type": dict(by_file_type),
                "by_doc_type": {}, "total_tables": 0}

    # 'edinburgh' users: stats from the bulk vectors-only corpus (chunk store),
    # so the home PROJECT LIBRARY widget reflects their own documents, not the demo.
    if _corpus_of(user) == "edinburgh":
        n = 0
        try:
            from src.chunk_store import get_chunk_store
            reg_names = {r.file_name for r in registry.get_completed()}
            con = get_chunk_store().connection()
            rows = con.execute(
                "SELECT DISTINCT file_name FROM chunks "
                "WHERE file_name IS NOT NULL AND file_name <> ''"
            ).fetchall()
            n = sum(1 for (fn,) in rows if fn not in reg_names)
        except Exception:
            n = 0

        # The spreadsheets live in the catalog, not the chunk store, so the
        # vectors-only count above misses them entirely. /library already
        # solves this with _edinburgh_data_library_docs(); reuse it rather
        # than reporting zero. This used to be hardcoded to 0 with the note
        # "bulk corpus has no spreadsheets" — true when written, false since
        # the Excel ingest, which left the home PROJECT LIBRARY widget
        # claiming 0 tables next to a sidebar listing 122 spreadsheets.
        data_docs = _edinburgh_data_library_docs()

        by_file_type: dict[str, int] = {}
        if n:
            by_file_type["document"] = n
        if data_docs:
            by_file_type["data"] = len(data_docs)

        return {
            "total_files": n + len(data_docs),
            "by_file_type": by_file_type,
            # Same label the registry branch uses for spreadsheets, so the
            # doc-type chips read consistently across corpora. The bulk
            # documents carry no notice metadata, so they stay unclassified
            # and roll into OTHER as before.
            "by_doc_type": {"data_file": len(data_docs)} if data_docs else {},
            "total_tables": sum(len(d.table_names) for d in data_docs),
        }

    # demo / default: registry stats (unchanged)
    completed = registry.get_completed()

    # Count by file_type (document/email/data)
    by_file_type = Counter(r.file_type for r in completed)

    # Count by doc_type from notice metadata (letter/notice/email/report/dpr etc.)
    by_doc_type: dict[str, int] = {}
    for r in completed:
        if r.notice_extracted:
            notice = _load_notice_metadata(r.doc_id)
            if notice and notice.doc_type:
                dt = notice.doc_type.lower().strip()
                by_doc_type[dt] = by_doc_type.get(dt, 0) + 1
            else:
                by_doc_type["unclassified"] = by_doc_type.get("unclassified", 0) + 1
        elif r.file_type == "data":
            by_doc_type["data_file"] = by_doc_type.get("data_file", 0) + 1
        else:
            by_doc_type["unclassified"] = by_doc_type.get("unclassified", 0) + 1

    # Count tables
    total_tables = sum(len(r.table_names) for r in completed)

    return {
        "total_files": len(completed),
        "by_file_type": dict(by_file_type),
        "by_doc_type": dict(sorted(by_doc_type.items(), key=lambda x: x[1], reverse=True)),
        "total_tables": total_tables,
    }


@router.get("/library/clusters", response_model=List[LibraryClusterSummary])
async def list_library_clusters(
    project: ProjectContext = Depends(get_current_project),
):
    """List topic clusters with doc counts and sample filenames."""
    from src.document_clusterer import get_clusterer
    from src.document_registry import get_document_registry

    clusterer = get_clusterer()
    registry = get_document_registry()

    # Build a quick map: cluster_id -> list of file_names (first 3)
    samples: dict[str, list[str]] = {}
    project_records = registry.get_completed(project_id=project.project_id)
    for r in project_records:
        cid = getattr(r, "cluster_id", None)
        if not cid:
            continue
        bucket = samples.setdefault(cid, [])
        if len(bucket) < 3:
            bucket.append(r.file_name)

    out: List[LibraryClusterSummary] = []
    allowed = set(samples)
    for c in clusterer.list_clusters():
        if c["cluster_id"] not in allowed:
            continue
        out.append(LibraryClusterSummary(
            cluster_id=c["cluster_id"],
            label=c["label"],
            doc_count=c["doc_count"],
            file_types=c["file_types"],
            sample_doc_names=samples.get(c["cluster_id"], []),
        ))
    return out


@router.post("/library/clusters/recompute")
async def recompute_library_clusters(
    force: bool = False,
    project: ProjectContext = Depends(get_current_project),
):
    """Trigger a full re-cluster in the background. Returns immediately."""
    from src.document_clusterer import get_clusterer

    clusterer = get_clusterer()
    thread = threading.Thread(
        target=clusterer.cluster_all,
        kwargs={"force": force, "project_id": project.project_id},
        daemon=True,
    )
    thread.start()
    return {"status": "scheduled", "force": force}


@router.get("/library/{doc_id}", response_model=LibraryDocument)
async def get_library_document(
    doc_id: str,
    project: ProjectContext = Depends(get_current_project),
):
    """Get a single document's metadata from the library."""
    from src.document_registry import get_document_registry
    registry = get_document_registry()
    rec = registry.get(doc_id)
    if not rec or (getattr(rec, "project_id", "") or "") != project.project_id:
        raise HTTPException(404, "Document not found in library")
    return _build_library_doc(rec)
