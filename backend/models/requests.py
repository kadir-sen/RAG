"""Request models for API endpoints."""

from typing import Any, List, Optional
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    conversation_id: str
    provider: Optional[str] = None
    doc_ids: Optional[List[str]] = None  # Scope query to specific documents
    email_ids: Optional[List[str]] = None  # Selected emails for correspondence mode
    mode: Optional[str] = None  # Frontend mode: 'chat', 'correspondence', 'document_analysis'
    request_id: Optional[str] = None  # Client-generated id to poll the live activity feed


class AnswerCitation(BaseModel):
    doc_name: str = ""
    anchor: str = ""
    snippet: str = ""


class AnswerDocumentRequest(BaseModel):
    """One answer, sent back for rendering as a Word document.

    The client posts what it is holding rather than the server rendering from a
    stored message id, because the server has strictly less: only the first 20
    preview rows are persisted and the row total is not, so a restored answer on
    disk cannot produce a better document than the one on screen. Posting also
    makes the download behave identically for a fresh answer and a reopened
    conversation, which is what was asked for — and it works for every
    conversation already written, which an id-based design would not.

    The endpoint is a formatter, not a data source: it reads nothing, and echoes
    only what the caller already had.
    """
    question: str = ""
    answer: str = ""
    citations: List[AnswerCitation] = []
    sql: str = ""
    table_columns: List[str] = []
    table_rows: List[List[Any]] = []
    # The query's true row count, when the caller knows it. Omitted on a restored
    # answer — the document then says how many rows it is showing and makes no
    # claim about the query.
    total_rows: Optional[int] = None


class ConversationCreate(BaseModel):
    title: str = "New Chat"


class ConversationRename(BaseModel):
    title: str


class AddDocumentsRequest(BaseModel):
    doc_ids: List[str]


class PinRequest(BaseModel):
    pinned: bool


class ArchiveRequest(BaseModel):
    archived: bool


class KnowledgeCollectionCreate(BaseModel):
    name: str
    description: str = ""


class KnowledgeCollectionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
