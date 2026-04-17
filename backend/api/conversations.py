"""CRUD endpoints for conversations."""

from fastapi import APIRouter, Depends, HTTPException
from typing import List

from backend.models.requests import (
    ConversationCreate,
    ConversationRename,
    AddDocumentsRequest,
    PinRequest,
    ArchiveRequest,
)
from backend.models.responses import ConversationMeta, ConversationOut, MessageOut, LibraryDocument
from backend.core.dependencies import get_conversation_store
from backend.services.response_builder import build_chat_response

router = APIRouter()


_LEGACY_QUERY_TYPE_MAP = {
    "answer": "document",
    "sql_result": "data",
    "doc_list": "timeline",
    "email_trace": "thread",
}


def _meta_to_out(c) -> ConversationMeta:
    return ConversationMeta(
        conversation_id=c.conversation_id,
        title=c.title,
        created_at=c.created_at,
        updated_at=c.updated_at,
        message_count=getattr(c, "message_count", 0),
        document_ids=getattr(c, "document_ids", []),
        pinned=getattr(c, "pinned", False),
        archived=getattr(c, "archived", False),
    )


@router.get("/conversations", response_model=List[ConversationMeta])
async def list_conversations(
    archived: bool = False, store=Depends(get_conversation_store)
):
    """List conversations. If archived=true, returns archived ones instead."""
    convs = store.list_archived() if archived else store.list_conversations()
    return [_meta_to_out(c) for c in convs]


@router.post("/conversations", response_model=ConversationMeta)
async def create_conversation(
    body: ConversationCreate, store=Depends(get_conversation_store)
):
    conv = store.create_conversation(body.title)
    return _meta_to_out(conv)


@router.get("/conversations/{conv_id}", response_model=ConversationOut)
async def get_conversation(conv_id: str, store=Depends(get_conversation_store)):
    conv = store.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    messages = []
    for m in conv.messages:
        response = None
        if m.role == "assistant":
            raw_query_type = _LEGACY_QUERY_TYPE_MAP.get(
                m.query_type or "",
                m.query_type or "document",
            )
            raw = {
                "query_type": raw_query_type,
                "answer": m.content,
                "sources": m.sources or [],
                "sql": m.sql,
                "result_data": m.result_data,
            }
            response = build_chat_response(raw)

        messages.append(MessageOut(
            role=m.role,
            content=m.content,
            timestamp=m.timestamp,
            query_type=m.query_type,
            response=response,
        ))
    return ConversationOut(
        conversation_id=conv.conversation_id,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=messages,
        document_ids=conv.document_ids,
    )


@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str, store=Depends(get_conversation_store)):
    store.delete_conversation(conv_id)
    return {"ok": True}


@router.patch("/conversations/{conv_id}")
async def rename_conversation(
    conv_id: str, body: ConversationRename, store=Depends(get_conversation_store)
):
    store.rename_conversation(conv_id, body.title)
    return {"ok": True}


@router.patch("/conversations/{conv_id}/pin", response_model=ConversationMeta)
async def pin_conversation(
    conv_id: str, body: PinRequest, store=Depends(get_conversation_store)
):
    meta = store.set_pinned(conv_id, body.pinned)
    if meta is None:
        raise HTTPException(404, "Conversation not found")
    return _meta_to_out(meta)


@router.patch("/conversations/{conv_id}/archive", response_model=ConversationMeta)
async def archive_conversation(
    conv_id: str, body: ArchiveRequest, store=Depends(get_conversation_store)
):
    meta = store.set_archived(conv_id, body.archived)
    if meta is None:
        raise HTTPException(404, "Conversation not found")
    return _meta_to_out(meta)


# ── Document scoping ──────────────────────────────────

@router.post("/conversations/{conv_id}/documents")
async def add_documents_to_conversation(
    conv_id: str, body: AddDocumentsRequest, store=Depends(get_conversation_store)
):
    """Add documents to a conversation's scope."""
    conv = store.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    for doc_id in body.doc_ids:
        store.add_document(conv_id, doc_id)
    return {"ok": True, "document_ids": store.get_document_ids(conv_id)}


@router.delete("/conversations/{conv_id}/documents/{doc_id}")
async def remove_document_from_conversation(
    conv_id: str, doc_id: str, store=Depends(get_conversation_store)
):
    """Remove a document from a conversation's scope."""
    store.remove_document(conv_id, doc_id)
    return {"ok": True}


@router.get("/conversations/{conv_id}/documents", response_model=List[LibraryDocument])
async def list_conversation_documents(
    conv_id: str, store=Depends(get_conversation_store)
):
    """List documents scoped to this conversation."""
    from src.document_registry import get_document_registry
    from backend.api.library import _build_library_doc
    doc_ids = store.get_document_ids(conv_id)
    registry = get_document_registry()
    result = []
    for did in doc_ids:
        rec = registry.get(did)
        if rec:
            result.append(_build_library_doc(rec))
    return result
