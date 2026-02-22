"""
Conversation Store - Persistent multi-conversation management.
Manages per-user conversation history as JSON files.
Pattern: Follows TableCatalog singleton + JSON persistence from catalog.py.
"""
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

from .config import CONVERSATIONS_DIR
from .logger import logger


@dataclass
class ConversationMeta:
    """Lightweight metadata for conversation index."""
    conversation_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int = 0
    pinned: bool = False


@dataclass
class Message:
    """A single chat message."""
    role: str
    content: str
    timestamp: str
    query_type: Optional[str] = None
    sources: Optional[List[Dict]] = None
    sql: Optional[str] = None
    result_data: Optional[List[Any]] = None
    dual_answers: Optional[Dict] = None


@dataclass
class Conversation:
    """Full conversation with messages."""
    conversation_id: str
    title: str
    created_at: str
    updated_at: str
    messages: List[Message] = field(default_factory=list)


class ConversationStore:
    """
    Manages per-user conversation persistence.
    JSON-file backed, one file per conversation.
    """

    def __init__(self, username: str):
        self.username = username
        self.user_dir = CONVERSATIONS_DIR / username
        self.user_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.user_dir / "conversations.json"
        self._index: List[ConversationMeta] = []
        self._load_index()

    def _load_index(self) -> None:
        """Load conversation index from disk."""
        if self.index_path.exists():
            try:
                data = json.loads(self.index_path.read_text(encoding="utf-8"))
                self._index = [ConversationMeta(**item) for item in data]
            except Exception as e:
                logger.warning(f"[ConvStore] Failed to load index for {self.username}: {e}")
                self._index = []
        else:
            # Try GCS sync if local is empty
            try:
                from .gcs_storage import sync_user_conversations_from_gcs
                sync_user_conversations_from_gcs(self.username)
                if self.index_path.exists():
                    data = json.loads(self.index_path.read_text(encoding="utf-8"))
                    self._index = [ConversationMeta(**item) for item in data]
            except Exception:
                self._index = []

    def _save_index(self) -> None:
        """Save conversation index to disk."""
        try:
            data = [asdict(meta) for meta in self._index]
            self.index_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"[ConvStore] Failed to save index: {e}")

    def _conv_path(self, conv_id: str) -> Path:
        """Get file path for a conversation."""
        return self.user_dir / f"{conv_id}.json"

    def _save_conversation(self, conv: Conversation) -> None:
        """Save a full conversation to disk."""
        try:
            data = {
                "conversation_id": conv.conversation_id,
                "title": conv.title,
                "created_at": conv.created_at,
                "updated_at": conv.updated_at,
                "messages": [asdict(m) for m in conv.messages],
            }
            self._conv_path(conv.conversation_id).write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"[ConvStore] Failed to save conversation {conv.conversation_id}: {e}")

    def _load_conversation(self, conv_id: str) -> Optional[Conversation]:
        """Load a full conversation from disk."""
        path = self._conv_path(conv_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            messages = [Message(**m) for m in data.get("messages", [])]
            return Conversation(
                conversation_id=data["conversation_id"],
                title=data["title"],
                created_at=data["created_at"],
                updated_at=data["updated_at"],
                messages=messages,
            )
        except Exception as e:
            logger.error(f"[ConvStore] Failed to load conversation {conv_id}: {e}")
            return None

    # ── CRUD ──────────────────────────────────────────────

    def create_conversation(self, title: str = "New Chat") -> ConversationMeta:
        """Create a new conversation."""
        conv_id = f"conv_{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()
        meta = ConversationMeta(
            conversation_id=conv_id,
            title=title,
            created_at=now,
            updated_at=now,
        )
        self._index.insert(0, meta)  # newest first
        conv = Conversation(
            conversation_id=conv_id,
            title=title,
            created_at=now,
            updated_at=now,
        )
        self._save_conversation(conv)
        self._save_index()
        logger.info(f"[ConvStore] Created conversation: {conv_id}")
        return meta

    def get_conversation(self, conv_id: str) -> Optional[Conversation]:
        """Get a full conversation by ID."""
        return self._load_conversation(conv_id)

    def list_conversations(self) -> List[ConversationMeta]:
        """List all conversations, newest first."""
        return list(self._index)

    def rename_conversation(self, conv_id: str, new_title: str) -> None:
        """Rename a conversation."""
        for meta in self._index:
            if meta.conversation_id == conv_id:
                meta.title = new_title
                meta.updated_at = datetime.now().isoformat()
                break
        self._save_index()

        conv = self._load_conversation(conv_id)
        if conv:
            conv.title = new_title
            conv.updated_at = datetime.now().isoformat()
            self._save_conversation(conv)

    def delete_conversation(self, conv_id: str) -> None:
        """Delete a conversation."""
        self._index = [m for m in self._index if m.conversation_id != conv_id]
        self._save_index()

        path = self._conv_path(conv_id)
        if path.exists():
            path.unlink()
        logger.info(f"[ConvStore] Deleted conversation: {conv_id}")

    # ── Messages ──────────────────────────────────────────

    def add_message(self, conv_id: str, message: Message) -> None:
        """Add a message to a conversation."""
        conv = self._load_conversation(conv_id)
        if not conv:
            return

        conv.messages.append(message)
        conv.updated_at = datetime.now().isoformat()
        self._save_conversation(conv)

        # Update index
        for meta in self._index:
            if meta.conversation_id == conv_id:
                meta.message_count = len(conv.messages)
                meta.updated_at = conv.updated_at
                break
        self._save_index()

    def get_recent_messages(self, conv_id: str, n: int = 6) -> List[Message]:
        """Get the last N messages from a conversation."""
        conv = self._load_conversation(conv_id)
        if not conv:
            return []
        return conv.messages[-n:]

    def auto_title(self, conv_id: str, first_message: str) -> str:
        """Generate title from first user message (no LLM call)."""
        title = first_message.strip()[:50]
        if len(first_message) > 50:
            title += "..."
        self.rename_conversation(conv_id, title)
        return title

    # ── GCS Sync ──────────────────────────────────────────

    def sync_to_gcs(self) -> None:
        """Upload all conversation files to GCS."""
        try:
            from .gcs_storage import sync_user_conversations_to_gcs
            sync_user_conversations_to_gcs(self.username)
        except Exception as e:
            logger.warning(f"[ConvStore] GCS sync failed: {e}")


def format_chat_context(
    messages: List[Message],
    max_messages: int = 6,
    max_chars: int = 8000,
) -> str:
    """
    Format recent messages as conversation context for LLM.
    Returns a string with <CONVERSATION_HISTORY> tags.
    """
    if not messages:
        return ""

    recent = messages[-max_messages:]
    lines = ["<CONVERSATION_HISTORY>"]
    total_chars = 0

    for msg in recent:
        role_label = "User" if msg.role == "user" else "Assistant"
        content = msg.content or ""

        # For dual-LLM answers, pick first provider's answer
        if msg.dual_answers:
            for provider_answer in msg.dual_answers.values():
                if isinstance(provider_answer, dict) and provider_answer.get("answer"):
                    content = provider_answer["answer"]
                    break

        # Truncate long answers
        if len(content) > 500:
            content = content[:500] + "..."

        line = f"{role_label}: {content}"
        total_chars += len(line)
        if total_chars > max_chars:
            break
        lines.append(line)

    lines.append("</CONVERSATION_HISTORY>")
    return "\n".join(lines)
