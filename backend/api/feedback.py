"""POST /api/feedback — capture 👍/👎 on assistant answers (data flywheel)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.core.dependencies import get_conversation_store
from backend.core.security import UserContext, get_current_user
from src.feedback_store import record_feedback, summary as feedback_summary

router = APIRouter()


class FeedbackRequest(BaseModel):
    conversation_id: str
    message_id: Optional[str] = None   # if omitted, the last assistant message is used
    vote: str                          # "up" | "down"
    note: Optional[str] = None
    correction: Optional[str] = None


@router.post("/feedback")
def submit_feedback(
    req: FeedbackRequest,
    user: UserContext = Depends(get_current_user),
    store=Depends(get_conversation_store),
) -> dict:
    """Record user feedback on an assistant answer, enriched with the question,
    route, sources and SQL the answer relied on (resolved from the conversation)."""
    if req.vote not in ("up", "down"):
        raise HTTPException(400, "vote must be 'up' or 'down'")

    conv = store.get_conversation(req.conversation_id)
    if not conv:
        raise HTTPException(404, "conversation_not_found")

    # Resolve the target assistant message (by id, else the most recent assistant turn).
    target = None
    if req.message_id:
        target = next(
            (m for m in conv.messages if getattr(m, "message_id", None) == req.message_id),
            None,
        )
    if target is None:
        target = next(
            (m for m in reversed(conv.messages) if m.role == "assistant"), None
        )
    if target is None:
        raise HTTPException(404, "no_assistant_message")

    # The question is the user turn immediately preceding the answer.
    question = ""
    idx = conv.messages.index(target)
    for m in reversed(conv.messages[:idx]):
        if m.role == "user":
            question = m.content
            break

    source_files = sorted({
        s.get("file_name") for s in (target.sources or []) if s.get("file_name")
    })

    record = record_feedback({
        "username": user.username,
        "conversation_id": req.conversation_id,
        "message_id": getattr(target, "message_id", None),
        "vote": req.vote,
        "note": req.note,
        "correction": req.correction,
        "question": question,
        "route": target.query_type,
        "sql": target.sql,
        "source_files": source_files,
    })
    return {"ok": True, "recorded_at": record.get("timestamp")}


@router.get("/feedback/summary")
def get_feedback_summary() -> dict:
    """Aggregate feedback counts (overall + per route). Admin/analytics view."""
    return feedback_summary()
