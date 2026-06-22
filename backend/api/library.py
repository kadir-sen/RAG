"""Library endpoints — global document registry."""

import os
import threading
from typing import List, Optional, Set

from fastapi import APIRouter, HTTPException

from backend.models.responses import (
    LibraryClusterSummary,
    LibraryDocument,
    NoticeMetadataOut,
)

router = APIRouter()

# Cap how many vectors-only (chunk-store) documents we surface in the library so
# a very large corpus (e.g. 7k+ Edinburgh Tram PDFs) doesn't render thousands of
# DOM nodes in the sidebar at once. Raise via env when a real search/filter lands.
_VECTORS_ONLY_LIMIT = int(os.getenv("LIBRARY_VECTORS_ONLY_LIMIT", "1000"))

_EMAIL_EXTS = {".eml", ".msg"}
_DATA_EXTS = {".xlsx", ".xls", ".csv"}


def _vectors_only_library_docs(known_names: Set[str],
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
    rows = con.execute(
        "SELECT file_name FROM chunks "
        "WHERE file_name IS NOT NULL AND file_name <> '' "
        "GROUP BY file_name ORDER BY file_name"
    ).fetchall()
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
async def list_library():
    """List all completed documents in the global library — registry records plus
    any vectors-only documents (bulk-ingested without a registry entry) so a large
    corpus is browsable and clickable in the sidebar."""
    from src.document_registry import get_document_registry
    registry = get_document_registry()
    docs = [_build_library_doc(r) for r in registry.get_completed()]
    try:
        known = {d.file_name for d in docs}
        docs += _vectors_only_library_docs(known)
    except Exception:
        pass  # never break the core list if the chunk store is unavailable
    return docs


@router.get("/library/summary")
async def library_summary():
    """Document classification summary — count by doc_type and file_type."""
    from src.document_registry import get_document_registry
    from collections import Counter

    registry = get_document_registry()
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
async def list_library_clusters():
    """List topic clusters with doc counts and sample filenames."""
    from src.document_clusterer import get_clusterer
    from src.document_registry import get_document_registry

    clusterer = get_clusterer()
    registry = get_document_registry()

    # Build a quick map: cluster_id -> list of file_names (first 3)
    samples: dict[str, list[str]] = {}
    for r in registry.get_completed():
        cid = getattr(r, "cluster_id", None)
        if not cid:
            continue
        bucket = samples.setdefault(cid, [])
        if len(bucket) < 3:
            bucket.append(r.file_name)

    out: List[LibraryClusterSummary] = []
    for c in clusterer.list_clusters():
        out.append(LibraryClusterSummary(
            cluster_id=c["cluster_id"],
            label=c["label"],
            doc_count=c["doc_count"],
            file_types=c["file_types"],
            sample_doc_names=samples.get(c["cluster_id"], []),
        ))
    return out


@router.post("/library/clusters/recompute")
async def recompute_library_clusters(force: bool = False):
    """Trigger a full re-cluster in the background. Returns immediately."""
    from src.document_clusterer import get_clusterer

    clusterer = get_clusterer()
    thread = threading.Thread(
        target=clusterer.cluster_all,
        kwargs={"force": force},
        daemon=True,
    )
    thread.start()
    return {"status": "scheduled", "force": force}


@router.get("/library/{doc_id}", response_model=LibraryDocument)
async def get_library_document(doc_id: str):
    """Get a single document's metadata from the library."""
    from src.document_registry import get_document_registry
    registry = get_document_registry()
    rec = registry.get(doc_id)
    if not rec:
        raise HTTPException(404, "Document not found in library")
    return _build_library_doc(rec)
