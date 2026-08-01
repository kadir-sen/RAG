"""Document content endpoint for the right-panel viewer."""

from fastapi import APIRouter, Depends, Query

from backend.core.projects import ProjectContext, get_current_project
from backend.models.responses import DocContent
from backend.services.document_service import DocumentService

router = APIRouter()
_doc_service = DocumentService()


@router.get("/docs/{doc_id}/content", response_model=DocContent)
async def get_doc_content(
    doc_id: str,
    anchor: str = Query(default="", description="e.g. page_3"),
    file_name: str = Query(
        default="",
        description="Fallback when doc_id no longer resolves. Older ids are an "
                    "md5 of the file path at ingest time, so they die whenever "
                    "the corpus is re-ingested or moved — the name does not.",
    ),
    project: ProjectContext = Depends(get_current_project),
):
    return await _doc_service.get_content(
        doc_id, anchor, file_name, project_id=project.project_id,
    )
