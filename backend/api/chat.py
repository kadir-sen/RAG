"""POST /api/chat — main chat endpoint."""

from fastapi import APIRouter, Depends, HTTPException

from backend.models.requests import AnswerDocumentRequest, ChatRequest
from backend.models.responses import ChatResponse, QueryProgressResponse, QueryActivityStep
from backend.core.dependencies import get_query_router, get_conversation_store
from backend.core.security import UserContext, get_current_user
from backend.core.projects import ProjectContext, get_current_project
from backend.services.chat_orchestrator import ChatOrchestrator
from backend.tasks.query_progress import query_progress

router = APIRouter()
_orchestrator = ChatOrchestrator()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    user: UserContext = Depends(get_current_user),
    query_router=Depends(get_query_router),
    store=Depends(get_conversation_store),
    project: ProjectContext = Depends(get_current_project),
):
    # Feature gating — correspondence mode is a per-user flag.
    if req.mode == "correspondence" and not user.features.get("correspondence", False):
        raise HTTPException(403, "feature_not_available:correspondence")
    return await _orchestrator.process(
        query=req.message,
        conversation_id=req.conversation_id,
        router=query_router,
        store=store,
        doc_ids=req.doc_ids,
        email_ids=req.email_ids,
        mode=req.mode,
        username=user.username,
        request_id=req.request_id,
        project_id=project.project_id,
        project_role=project.role,
    )


@router.get("/chat/progress/{request_id}", response_model=QueryProgressResponse)
async def chat_progress(
    request_id: str,
    user: UserContext = Depends(get_current_user),
):
    """Live activity feed for an in-flight query. The client polls this with the
    same request_id it sent to POST /chat while the answer is being produced."""
    act = query_progress.get(request_id)
    if act is None:
        return QueryProgressResponse(request_id=request_id, steps=[], done=False)
    return QueryProgressResponse(
        request_id=request_id,
        steps=[QueryActivityStep(seq=s.seq, ts=s.ts, kind=s.kind, label=s.label, detail=s.detail)
               for s in act.steps],
        done=act.done,
    )


@router.post("/chat/document")
async def chat_answer_document(
    req: AnswerDocumentRequest,
    _: UserContext = Depends(get_current_user),
):
    """One answer as a Word document.

    The caller posts what it is holding rather than naming a stored message,
    because the server has strictly less of it: only the first 20 preview rows
    are persisted and the row total is not, so rendering from disk could not
    produce a better document — and an id-based route would not work at all for
    the conversations already written. Posting also makes the download behave the
    same for a fresh answer and a reopened one, which is the requirement.

    So this is a formatter: it reads no corpus, touches no filesystem, and echoes
    only what the caller already had. The caps in src/answer_docx are what keep
    that from becoming a way to make the box do arbitrary work, and rendering
    runs in a thread so a long answer cannot block the event loop.
    """
    import asyncio

    from src.answer_docx import answer_filename, build_answer_docx

    from ._docx import docx_response

    blob = await asyncio.to_thread(
        build_answer_docx,
        req.question,
        req.answer,
        citations=[c.model_dump() for c in req.citations],
        sql=req.sql,
        table_columns=req.table_columns,
        table_rows=req.table_rows,
        total_rows=req.total_rows,
    )
    return docx_response(blob, answer_filename(req.question))
