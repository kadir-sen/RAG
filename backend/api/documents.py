"""Document content endpoint for the right-panel viewer."""

from fastapi import APIRouter, Query

from backend.models.responses import DocContent
from backend.services.document_service import DocumentService

router = APIRouter()
_doc_service = DocumentService()


@router.get("/docs/{doc_id}/content", response_model=DocContent)
async def get_doc_content(
    doc_id: str,
    anchor: str = Query(default="", description="e.g. page_3"),
):
    return await _doc_service.get_content(doc_id, anchor)
