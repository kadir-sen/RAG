"""Request models for API endpoints."""

from typing import List, Optional
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    conversation_id: str
    provider: Optional[str] = None
    doc_ids: Optional[List[str]] = None  # Scope query to specific documents
    email_ids: Optional[List[str]] = None  # Selected emails for correspondence mode


class ConversationCreate(BaseModel):
    title: str = "New Chat"


class ConversationRename(BaseModel):
    title: str


class AddDocumentsRequest(BaseModel):
    doc_ids: List[str]
