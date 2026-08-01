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
from dataclasses import dataclass, field, fields, asdict

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
    archived: bool = False
    project_id: str = ""


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
    # Stable id so user feedback (👍/👎) can reference a specific assistant answer.
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class Conversation:
    """Full conversation with messages."""
    conversation_id: str
    title: str
    created_at: str
    updated_at: str
    messages: List[Message] = field(default_factory=list)
    document_ids: List[str] = field(default_factory=list)
    project_id: str = ""


class ConversationStore:
    """
    Manages per-user conversation persistence.
    JSON-file backed, one file per conversation.
    """

    def __init__(self, username: str, project_id: str = ""):
        self.username = username
        self.project_id = project_id
        # Backwards compatible for maintenance scripts/tests that intentionally
        # open the old unscoped store; authenticated API requests always pass a
        # project and therefore use a separate directory.
        self.user_dir = (CONVERSATIONS_DIR / username / project_id
                         if project_id else CONVERSATIONS_DIR / username)
        self.user_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.user_dir / "conversations.json"
        self._index: List[ConversationMeta] = []
        # False means "we could not establish what is on disk this request".
        # _save_index refuses to write in that state, so a read error can never
        # truncate the index.
        self._index_loaded = False
        self._load_index()

    def _load_index(self) -> None:
        """Load the conversation index, tolerating damage rather than erasing it.

        Four outcomes, none of which loses a conversation:
          * parses              → per-record load; a bad record costs one entry
          * parses after repair → repaired copy written, original kept as .corrupt.bak
          * unrepairable        → quarantined, index rebuilt from the files on disk
          * unreadable (I/O)    → _index_loaded stays False; nothing may be written

        The old version set ``self._index = []`` on ANY exception and left saving
        enabled, so a single quoted character in a title (auto_title takes the
        user's first 50 characters) would delist every prior conversation on the
        next create/rename/delete. Same shape the registry loader already fixed.
        """
        if not self.index_path.exists():
            try:
                from .gcs_storage import sync_user_conversations_from_gcs
                sync_user_conversations_from_gcs(self.username)
            except Exception:
                pass
            if not self.index_path.exists():
                self._index = []
                self._index_loaded = True      # a genuinely absent index IS empty
                return

        try:
            raw = self.index_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"[ConvStore] Cannot read index for {self.username}: {e}")
            self._index = []
            self._index_loaded = False         # refuse to write over what we cannot read
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            from .json_repair import repair_file, repair_json_text
            data, _ = repair_json_text(raw)
            if data is None or not isinstance(data, list):
                logger.error(
                    f"[ConvStore] Index for {self.username} is unrepairable ({e}); "
                    f"quarantining it and rebuilding from the files on disk"
                )
                self._quarantine_index()
                self._index = self._rebuild_index_from_files()
                self._index_loaded = True
                self._save_index()
                return
            repair_file(self.index_path)       # persist the repair + .corrupt.bak
            logger.warning(f"[ConvStore] Recovered corrupt index for {self.username}")

        if not isinstance(data, list):
            logger.error(
                f"[ConvStore] Index for {self.username} is not a list "
                f"({type(data).__name__}) — rebuilding from disk"
            )
            self._quarantine_index()
            self._index = self._rebuild_index_from_files()
            self._index_loaded = True
            self._save_index()
            return

        kept, failed = [], 0
        for item in data:
            # Per record, so one malformed entry costs one conversation rather
            # than every conversation in the file.
            try:
                meta = self._meta_from_dict(item)
            except Exception as e:
                failed += 1
                logger.warning(f"[ConvStore] Skipping unreadable index record: {e}")
                continue
            if meta is not None:
                kept.append(meta)
            else:
                failed += 1
        self._index = kept
        self._index_loaded = True
        if failed:
            logger.warning(
                f"[ConvStore] {failed} index record(s) could not be loaded for "
                f"{self.username}; {len(kept)} kept"
            )
        self._prune_index()

    def _quarantine_index(self) -> None:
        """Move an unusable index aside instead of overwriting it."""
        try:
            import shutil
            from .json_repair import BACKUP_SUFFIX
            dest = self.index_path.with_name(self.index_path.name + BACKUP_SUFFIX)
            if not dest.exists():
                shutil.copy2(self.index_path, dest)
                logger.warning(f"[ConvStore] Original index preserved at {dest.name}")
        except Exception as e:
            logger.error(f"[ConvStore] Could not quarantine index: {e}")

    def _rebuild_index_from_files(self) -> List[ConversationMeta]:
        """Reconstruct the index from the per-conversation files themselves.

        Every field ConversationMeta needs is already in each conversation file,
        so an unusable index is a recoverable condition rather than data loss.
        `pinned`/`archived` are not stored per conversation and fall back to
        their defaults.
        """
        rebuilt: List[ConversationMeta] = []
        for path in sorted(self.user_dir.glob("conv_*.json")):
            conv = self._load_conversation(path.stem)
            if conv is None:
                continue
            rebuilt.append(ConversationMeta(
                conversation_id=conv.conversation_id or path.stem,
                title=conv.title or "Recovered chat",
                created_at=conv.created_at or "",
                updated_at=conv.updated_at or conv.created_at or "",
                message_count=len(conv.messages),
            ))
        logger.warning(
            f"[ConvStore] Rebuilt index for {self.username} from disk: "
            f"{len(rebuilt)} conversation(s)"
        )
        return rebuilt

    def _prune_index(self) -> None:
        """Drop index entries whose conversation file no longer exists.

        The index and the per-conversation files can drift apart (partial GCS
        sync, storage resets between deploys). A ghost entry renders in the
        sidebar but 404s on open — prune it here so the list only ever shows
        openable conversations.
        """
        ghosts = [m for m in self._index if not self._conv_path(m.conversation_id).exists()]
        if not ghosts:
            return
        # An index with entries but a directory holding no conversation files at
        # all is not "the user deleted everything" — it is a storage volume that
        # did not mount (docker-compose.prod.yml binds ./storage:/app/storage).
        # Pruning here would erase every user's history on the first request.
        if not any(self.user_dir.glob("conv_*.json")):
            logger.error(
                f"[ConvStore] {len(self._index)} indexed conversations for "
                f"{self.username} but no conversation files on disk — refusing "
                f"to prune (the storage volume is probably not mounted)"
            )
            return
        for meta in ghosts:
            logger.warning(
                f"[ConvStore] Pruning ghost conversation {meta.conversation_id} "
                f"('{meta.title}') for {self.username}: file missing"
            )
        self._index = [m for m in self._index if self._conv_path(m.conversation_id).exists()]
        self._save_index()
        self.sync_to_gcs()

    @staticmethod
    def _meta_from_dict(item: Dict[str, Any]) -> Optional[ConversationMeta]:
        """Backward-compatible loader. Returns None for a record with no id.

        The hard ``item["conversation_id"]`` used to raise out of the enclosing
        list comprehension, so one bad record emptied the entire index.
        """
        if not isinstance(item, dict):
            return None
        conv_id = item.get("conversation_id")
        if not conv_id:
            return None
        return ConversationMeta(
            conversation_id=conv_id,
            title=item.get("title", "") or "",
            created_at=item.get("created_at", "") or "",
            updated_at=item.get("updated_at", "") or "",
            message_count=item.get("message_count", 0) or 0,
            pinned=bool(item.get("pinned", False)),
            archived=bool(item.get("archived", False)),
            project_id=item.get("project_id", "") or "",
        )

    def _save_index(self) -> None:
        """Save the index. Refuses when the load did not succeed.

        This file is rewritten in full every time, so saving over an index we
        failed to read would truncate it — a read error must never become a
        write. Written through a temp file so a crash mid-write cannot leave a
        torn index either.
        """
        if not self._index_loaded:
            logger.error(
                f"[ConvStore] Refusing to save the index for {self.username}: "
                f"the on-disk index could not be read, and writing now would "
                f"truncate it"
            )
            return
        try:
            data = [asdict(meta) for meta in self._index]
            tmp = self.index_path.with_name(self.index_path.name + ".tmp")
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self.index_path)       # atomic
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
                "document_ids": conv.document_ids,
                "project_id": conv.project_id or self.project_id,
            }
            # Written through a temp file and moved into place: a crash partway
            # through a large answer would otherwise leave a half-written file,
            # which reads exactly like the corruption this release repairs.
            dest = self._conv_path(conv.conversation_id)
            tmp = dest.with_name(dest.name + ".tmp")
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(dest)                  # atomic
        except Exception as e:
            logger.error(f"[ConvStore] Failed to save conversation {conv.conversation_id}: {e}")

    def _load_conversation(self, conv_id: str) -> Optional[Conversation]:
        """Load a full conversation from disk, repairing it if it is damaged."""
        path = self._conv_path(conv_id)
        if not path.exists():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"[ConvStore] Cannot read conversation {conv_id}: {e}")
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            # A file mangled by the old path normalizer is recoverable data, not
            # a lost conversation. Repair it (the original is kept beside it)
            # and carry on; give up only when the repair cannot be verified.
            from .json_repair import (
                conversation_looks_sane, repair_file, repair_json_text,
            )
            data, _ = repair_json_text(raw)
            if data is None or not conversation_looks_sane(data):
                logger.error(
                    f"[ConvStore] {conv_id} is corrupt and unrepairable ({e}); "
                    f"the file is left on disk untouched"
                )
                return None
            repair_file(path)
            logger.warning(f"[ConvStore] Recovered corrupt conversation {conv_id} on read")
        try:
            raw_msgs = data.get("messages", [])
            # Backward-compatible message loader: files written by older app
            # versions can carry extra keys the current dataclass doesn't
            # accept — Message(**m) would raise and the whole conversation
            # would 404 even though the file is fine. Ignore unknown keys,
            # like _meta_from_dict does for the index.
            msg_fields = {f.name for f in fields(Message)}
            messages = []
            for m in raw_msgs:
                if not isinstance(m, dict) or m.get("role") is None:
                    continue
                kwargs = {k: v for k, v in m.items() if k in msg_fields}
                kwargs.setdefault("content", "")
                kwargs.setdefault("timestamp", "")
                messages.append(Message(**kwargs))
            # Loud warning when a conversation file claims to belong to a
            # non-empty history but actually persists no messages. This is the
            # signature of the "clicking an old chat opens WelcomeScreen" bug;
            # surfacing it here makes the broken records discoverable from logs.
            if not messages and (data.get("message_count") or 0) > 0:
                logger.warning(
                    f"[ConvStore] {conv_id} has empty messages array but "
                    f"message_count={data.get('message_count')} — file may be "
                    f"corrupt or partially synced"
                )
            # Top-level fields are tolerant too: legacy files may miss any of
            # them, and a KeyError here 404s a conversation whose file exists.
            return Conversation(
                conversation_id=data.get("conversation_id", conv_id),
                title=data.get("title", ""),
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
                messages=messages,
                document_ids=data.get("document_ids", []),
                project_id=data.get("project_id", "") or self.project_id,
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
            project_id=self.project_id,
        )
        self._index.insert(0, meta)  # newest first
        conv = Conversation(
            conversation_id=conv_id,
            title=title,
            created_at=now,
            updated_at=now,
            project_id=self.project_id,
        )
        self._save_conversation(conv)
        self._save_index()
        self.sync_to_gcs()
        logger.info(f"[ConvStore] Created conversation: {conv_id}")
        return meta

    def get_conversation(self, conv_id: str) -> Optional[Conversation]:
        """Get a full conversation by ID."""
        return self._load_conversation(conv_id)

    def drop_ghost_entry(self, conv_id: str) -> None:
        """Remove an index entry ONLY when its conversation file is missing.

        This used to also delist a file that existed but failed to parse, and
        that was the delete path: the old path normalizer corrupted the JSON,
        _load_conversation returned None, the API called this, the entry left
        the index — and the file stayed on disk, unreachable, because nothing in
        the UI can reach an id that is not in the index. Opening an old chat
        deleted it. Reproduced on production: a list of 7 became 6 by clicking.

        A file that exists is recoverable data (src/json_repair.py). Only a
        genuinely absent file is a ghost.
        """
        if self._conv_path(conv_id).exists():
            logger.error(
                f"[ConvStore] {conv_id} exists on disk but could not be served "
                f"for {self.username} — keeping the index entry; the file is "
                f"recoverable and must not be delisted"
            )
            return
        before = len(self._index)
        self._index = [m for m in self._index if m.conversation_id != conv_id]
        if len(self._index) != before:
            logger.warning(f"[ConvStore] Dropped ghost index entry {conv_id} for {self.username}")
            self._save_index()
            self.sync_to_gcs()

    def adopt_orphans(self) -> int:
        """Re-list conversation files that exist on disk but are not in the index.

        `drop_ghost_entry` used to delist any conversation whose file failed to
        parse, leaving the file behind and unreachable. Now that those files
        parse again, put them back — repairing a file does not make it visible,
        because nothing in the UI can reach an id that is not in the index.

        Only files that actually hold messages are adopted. On this corpus 179
        of 181 orphans are empty "New Chat" shells the user never typed into,
        and re-listing those would bury the real history under empty rows.
        """
        if not self._index_loaded:
            return 0
        known = {m.conversation_id for m in self._index}
        adopted = 0
        for path in sorted(self.user_dir.glob("conv_*.json")):
            conv_id = path.stem
            if conv_id in known:
                continue
            conv = self._load_conversation(conv_id)
            if conv is None or not conv.messages:
                continue
            self._index.append(ConversationMeta(
                conversation_id=conv_id,
                title=conv.title or "Recovered chat",
                created_at=conv.created_at or "",
                updated_at=conv.updated_at or conv.created_at or "",
                message_count=len(conv.messages),
            ))
            adopted += 1
            logger.warning(
                f"[ConvStore] Re-listed orphaned conversation {conv_id} "
                f"('{conv.title}', {len(conv.messages)} messages) for {self.username}"
            )
        if adopted:
            self._save_index()
            self.sync_to_gcs()
        return adopted

    def list_conversations(self, include_archived: bool = False) -> List[ConversationMeta]:
        """
        List conversations. Pinned first, then by recency.
        Archived conversations are excluded unless include_archived=True.
        """
        items = [m for m in self._index if include_archived or not m.archived]
        # Stable sort: by updated_at desc first, then by pinned desc.
        # Pinned items end up on top, each group sorted by recency.
        items.sort(key=lambda m: m.updated_at, reverse=True)
        items.sort(key=lambda m: m.pinned, reverse=True)
        return items

    def list_archived(self) -> List[ConversationMeta]:
        """List only archived conversations, most recently updated first."""
        items = [m for m in self._index if m.archived]
        items.sort(key=lambda m: m.updated_at, reverse=True)
        return items

    def set_pinned(self, conv_id: str, pinned: bool) -> Optional[ConversationMeta]:
        """Pin or unpin a conversation. Returns updated meta or None if not found."""
        for meta in self._index:
            if meta.conversation_id == conv_id:
                meta.pinned = bool(pinned)
                meta.updated_at = datetime.now().isoformat()
                self._save_index()
                self.sync_to_gcs()
                return meta
        return None

    def set_archived(self, conv_id: str, archived: bool) -> Optional[ConversationMeta]:
        """Archive or unarchive a conversation. Returns updated meta or None if not found."""
        for meta in self._index:
            if meta.conversation_id == conv_id:
                meta.archived = bool(archived)
                # Archiving also unpins
                if archived:
                    meta.pinned = False
                meta.updated_at = datetime.now().isoformat()
                self._save_index()
                self.sync_to_gcs()
                return meta
        return None

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
        self.sync_to_gcs()
        logger.info(f"[ConvStore] Deleted conversation: {conv_id}")

    # ── Document scoping ─────────────────────────────────

    def add_document(self, conv_id: str, doc_id: str) -> None:
        """Add a document to a conversation's scope."""
        conv = self._load_conversation(conv_id)
        if not conv:
            return
        if doc_id not in conv.document_ids:
            conv.document_ids.append(doc_id)
            conv.updated_at = datetime.now().isoformat()
            self._save_conversation(conv)

    def remove_document(self, conv_id: str, doc_id: str) -> None:
        """Remove a document from a conversation's scope."""
        conv = self._load_conversation(conv_id)
        if not conv:
            return
        if doc_id in conv.document_ids:
            conv.document_ids.remove(doc_id)
            conv.updated_at = datetime.now().isoformat()
            self._save_conversation(conv)

    def get_document_ids(self, conv_id: str) -> List[str]:
        """Get all document IDs scoped to a conversation."""
        conv = self._load_conversation(conv_id)
        if not conv:
            return []
        return list(conv.document_ids)

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

        # Persist to GCS for Cloud Run durability
        self.sync_to_gcs()

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
    max_messages: int = 10,
    max_chars: int = 12000,
) -> str:
    """
    Format recent messages as conversation context for LLM.
    Returns a string with <CONVERSATION_HISTORY> tags.
    Includes full assistant text, SQL table info, and query type.
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

        # Rich context for assistant messages
        if msg.role == "assistant":
            parts = []

            # Query type badge
            if msg.query_type:
                parts.append(f"[{msg.query_type.upper()}]")

            # Full text (no truncation - max_chars guards total size)
            parts.append(content)

            # SQL table info
            if msg.sql:
                table_name = _extract_table_from_sql(msg.sql)
                parts.append(f"(SQL query on table: {table_name})")

            content = " ".join(parts)

        line = f"{role_label}: {content}"
        total_chars += len(line)
        if total_chars > max_chars:
            break
        lines.append(line)

    lines.append("</CONVERSATION_HISTORY>")
    return "\n".join(lines)


def _extract_table_from_sql(sql: str) -> str:
    """Extract table name from SQL query."""
    import re
    match = re.search(r'\bFROM\s+"?(\w+)"?', sql, re.IGNORECASE)
    return match.group(1) if match else "unknown"
