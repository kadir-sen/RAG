"""Library endpoints — global document registry."""

from typing import List, Optional

from fastapi import APIRouter, HTTPException

from backend.models.responses import LibraryDocument, NoticeMetadataOut

router = APIRouter()


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
    )


@router.get("/library", response_model=List[LibraryDocument])
async def list_library():
    """List all completed documents in the global library."""
    from src.document_registry import get_document_registry
    registry = get_document_registry()
    return [_build_library_doc(r) for r in registry.get_completed()]


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


@router.get("/library/{doc_id}", response_model=LibraryDocument)
async def get_library_document(doc_id: str):
    """Get a single document's metadata from the library."""
    from src.document_registry import get_document_registry
    registry = get_document_registry()
    rec = registry.get(doc_id)
    if not rec:
        raise HTTPException(404, "Document not found in library")
    return _build_library_doc(rec)
