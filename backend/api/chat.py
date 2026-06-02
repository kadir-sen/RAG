"""POST /api/chat — main chat endpoint."""

from fastapi import APIRouter, Depends, HTTPException

from backend.models.requests import ChatRequest
from backend.models.responses import ChatResponse
from backend.core.dependencies import get_query_router, get_conversation_store
from backend.core.security import UserContext, get_current_user
from backend.services.chat_orchestrator import ChatOrchestrator

router = APIRouter()
_orchestrator = ChatOrchestrator()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    user: UserContext = Depends(get_current_user),
    query_router=Depends(get_query_router),
    store=Depends(get_conversation_store),
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
    )
