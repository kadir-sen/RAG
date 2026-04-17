"""Response contract models — every chat response follows this shape."""

from typing import List, Optional
from pydantic import BaseModel, Field


class NoticeMetadataOut(BaseModel):
    date: str = ""
    sender: str = ""
    sender_company: str = ""
    recipient: str = ""
    subject: str = ""
    doc_type: str = ""
    direction: str = ""
    ref_numbers: List[str] = Field(default_factory=list)
    summary: str = ""


class Citation(BaseModel):
    doc_id: str = ""
    doc_name: str = ""
    anchor: str = ""           # e.g. "page_3" for viewer navigation
    snippet: str = ""
    score: Optional[float] = None


class RelatedDoc(BaseModel):
    doc_id: str = ""
    doc_name: str = ""
    date: str = ""
    doc_type: str = ""
    reason: str = ""
    score: Optional[float] = None
    sender: str = ""
    recipient: str = ""


class SQLArtifact(BaseModel):
    generated_sql: str = ""
    tables_used: List[str] = Field(default_factory=list)
    row_count: int = 0
    preview_rows: List[dict] = Field(default_factory=list)
    source_file_id: str = ""
    source_file_name: str = ""


class ProviderAnswer(BaseModel):
    """A single provider's answer for multi-LLM comparison."""
    provider: str              # "gemini", "openai", "claude"
    model: str = ""            # "gemini-2.5-flash", "gpt-4o-mini", etc.
    text: str = ""
    sql: Optional[str] = None
    sql_artifact: Optional[SQLArtifact] = None


class ChatResponse(BaseModel):
    ui_intent: str       # "answer" | "doc_list" | "email_trace" | "sql_result"
    assistant_text: str
    citations: List[Citation] = Field(default_factory=list)
    related_docs: List[RelatedDoc] = Field(default_factory=list)
    sql_artifact: Optional[SQLArtifact] = None
    provider_answers: List[ProviderAnswer] = Field(default_factory=list)
    routing_confidence: Optional[float] = None  # 0.0-1.0, shown to user when low


class ConversationMeta(BaseModel):
    conversation_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    document_ids: List[str] = Field(default_factory=list)
    pinned: bool = False
    archived: bool = False


class MessageOut(BaseModel):
    role: str
    content: str
    timestamp: str
    query_type: Optional[str] = None
    response: Optional[ChatResponse] = None


class ConversationOut(BaseModel):
    conversation_id: str
    title: str
    created_at: str
    updated_at: str
    messages: List[MessageOut] = Field(default_factory=list)
    document_ids: List[str] = Field(default_factory=list)


class FileInfo(BaseModel):
    id: str
    name: str
    file_type: str = ""
    pages: Optional[int] = None
    ocr_pages: int = 0
    tables: int = 0
    rows: int = 0
    notice_extracted: bool = False
    status: str = "completed"


class UploadResult(BaseModel):
    file_id: str
    filename: str
    status: str = "indexing"


class IndexingStatus(BaseModel):
    file_id: str
    filename: str
    status: str = "pending"       # pending | indexing | completed | error
    progress: float = 0.0
    error: Optional[str] = None
    details: dict = Field(default_factory=dict)


class LibraryDocument(BaseModel):
    doc_id: str
    file_name: str
    file_type: str = ""
    extension: str = ""
    status: str = "processing"
    file_size_kb: int = 0
    table_names: List[str] = Field(default_factory=list)
    notice_extracted: bool = False
    created_at: str = ""
    notice_metadata: Optional[NoticeMetadataOut] = None


class KnowledgeCollectionOut(BaseModel):
    collection_id: str
    name: str
    description: str = ""
    document_ids: List[str] = Field(default_factory=list)
    document_count: int = 0
    created_at: str = ""
    updated_at: str = ""


class KnowledgeCollectionDetail(BaseModel):
    collection_id: str
    name: str
    description: str = ""
    document_ids: List[str] = Field(default_factory=list)
    documents: List[LibraryDocument] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


class DocContent(BaseModel):
    type: str                     # "pdf" | "table" | "text"
    file_name: str = ""
    page: int = 1
    total_pages: int = 1
    image_base64: str = ""
    text: str = ""
    columns: List[str] = Field(default_factory=list)
    rows: List[dict] = Field(default_factory=list)
    total_rows: int = 0
    error: Optional[str] = None
