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


@router.get("/library/{doc_id}", response_model=LibraryDocument)
async def get_library_document(doc_id: str):
    """Get a single document's metadata from the library."""
    from src.document_registry import get_document_registry
    registry = get_document_registry()
    rec = registry.get(doc_id)
    if not rec:
        raise HTTPException(404, "Document not found in library")
    return _build_library_doc(rec)
