"""Knowledge Collection endpoints — named groups of documents for RAG scoping."""

from typing import List

from fastapi import APIRouter, HTTPException

from backend.models.requests import (
    KnowledgeCollectionCreate,
    KnowledgeCollectionUpdate,
    AddDocumentsRequest,
)
from backend.models.responses import (
    KnowledgeCollectionOut,
    KnowledgeCollectionDetail,
)

router = APIRouter()


def _to_out(col) -> KnowledgeCollectionOut:
    return KnowledgeCollectionOut(
        collection_id=col.collection_id,
        name=col.name,
        description=col.description or "",
        document_ids=list(col.document_ids or []),
        document_count=len(col.document_ids or []),
        created_at=col.created_at or "",
        updated_at=col.updated_at or "",
    )


def _to_detail(col) -> KnowledgeCollectionDetail:
    from src.document_registry import get_document_registry
    from backend.api.library import _build_library_doc

    registry = get_document_registry()
    docs = []
    for did in col.document_ids or []:
        rec = registry.get(did)
        if rec:
            docs.append(_build_library_doc(rec))
    return KnowledgeCollectionDetail(
        collection_id=col.collection_id,
        name=col.name,
        description=col.description or "",
        document_ids=list(col.document_ids or []),
        documents=docs,
        created_at=col.created_at or "",
        updated_at=col.updated_at or "",
    )


@router.get("/knowledge", response_model=List[KnowledgeCollectionOut])
async def list_collections():
    from src.knowledge_store import get_knowledge_store
    return [_to_out(c) for c in get_knowledge_store().list_all()]


@router.post("/knowledge", response_model=KnowledgeCollectionOut)
async def create_collection(body: KnowledgeCollectionCreate):
    from src.knowledge_store import get_knowledge_store
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "Collection name cannot be empty")
    col = get_knowledge_store().create(name=name, description=body.description or "")
    return _to_out(col)


@router.get("/knowledge/{col_id}", response_model=KnowledgeCollectionDetail)
async def get_collection(col_id: str):
    from src.knowledge_store import get_knowledge_store
    col = get_knowledge_store().get(col_id)
    if not col:
        raise HTTPException(404, "Collection not found")
    return _to_detail(col)


@router.patch("/knowledge/{col_id}", response_model=KnowledgeCollectionOut)
async def update_collection(col_id: str, body: KnowledgeCollectionUpdate):
    from src.knowledge_store import get_knowledge_store
    col = get_knowledge_store().update(
        col_id, name=body.name, description=body.description
    )
    if not col:
        raise HTTPException(404, "Collection not found")
    return _to_out(col)


@router.delete("/knowledge/{col_id}")
async def delete_collection(col_id: str):
    from src.knowledge_store import get_knowledge_store
    ok = get_knowledge_store().delete(col_id)
    if not ok:
        raise HTTPException(404, "Collection not found")
    return {"ok": True}


@router.post("/knowledge/{col_id}/documents", response_model=KnowledgeCollectionOut)
async def add_documents(col_id: str, body: AddDocumentsRequest):
    from src.knowledge_store import get_knowledge_store
    from src.document_registry import get_document_registry

    registry = get_document_registry()
    valid_ids = [d for d in body.doc_ids if registry.get(d) is not None]
    col = get_knowledge_store().add_documents(col_id, valid_ids)
    if not col:
        raise HTTPException(404, "Collection not found")
    return _to_out(col)


@router.delete("/knowledge/{col_id}/documents/{doc_id}", response_model=KnowledgeCollectionOut)
async def remove_document(col_id: str, doc_id: str):
    from src.knowledge_store import get_knowledge_store
    col = get_knowledge_store().remove_document(col_id, doc_id)
    if not col:
        raise HTTPException(404, "Collection not found")
    return _to_out(col)
