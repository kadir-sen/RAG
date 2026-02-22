"""Tests for conversation store and session management."""
import json
import shutil
import time
from pathlib import Path

import pytest

from src.conversation_store import (
    ConversationStore,
    ConversationMeta,
    Message,
    Conversation,
    format_chat_context,
)


@pytest.fixture
def tmp_conv_dir(tmp_path, monkeypatch):
    """Override CONVERSATIONS_DIR to use temp directory."""
    monkeypatch.setattr("src.conversation_store.CONVERSATIONS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def store(tmp_conv_dir):
    """Create a ConversationStore with temp storage."""
    return ConversationStore("testuser")


# ── ConversationStore CRUD Tests ──────────────────────────


class TestConversationStoreCRUD:
    def test_create_conversation(self, store):
        meta = store.create_conversation("Test Chat")
        assert meta.conversation_id.startswith("conv_")
        assert meta.title == "Test Chat"
        assert meta.message_count == 0

    def test_create_conversation_default_title(self, store):
        meta = store.create_conversation()
        assert meta.title == "New Chat"

    def test_list_conversations_newest_first(self, store):
        store.create_conversation("First")
        store.create_conversation("Second")
        store.create_conversation("Third")

        convs = store.list_conversations()
        assert len(convs) == 3
        assert convs[0].title == "Third"
        assert convs[2].title == "First"

    def test_get_conversation(self, store):
        meta = store.create_conversation("My Chat")
        conv = store.get_conversation(meta.conversation_id)
        assert conv is not None
        assert conv.title == "My Chat"
        assert conv.messages == []

    def test_get_nonexistent_conversation(self, store):
        assert store.get_conversation("conv_nonexistent") is None

    def test_rename_conversation(self, store):
        meta = store.create_conversation("Old Name")
        store.rename_conversation(meta.conversation_id, "New Name")

        convs = store.list_conversations()
        assert convs[0].title == "New Name"

        conv = store.get_conversation(meta.conversation_id)
        assert conv.title == "New Name"

    def test_delete_conversation(self, store, tmp_conv_dir):
        meta = store.create_conversation("To Delete")
        conv_path = tmp_conv_dir / "testuser" / f"{meta.conversation_id}.json"
        assert conv_path.exists()

        store.delete_conversation(meta.conversation_id)

        assert len(store.list_conversations()) == 0
        assert not conv_path.exists()

    def test_delete_nonexistent_does_not_crash(self, store):
        store.delete_conversation("conv_nonexistent")
        assert len(store.list_conversations()) == 0


# ── Message Tests ─────────────────────────────────────────


class TestMessages:
    def test_add_message(self, store):
        meta = store.create_conversation("Chat")
        msg = Message(role="user", content="Hello", timestamp="2026-02-21T10:00:00")
        store.add_message(meta.conversation_id, msg)

        conv = store.get_conversation(meta.conversation_id)
        assert len(conv.messages) == 1
        assert conv.messages[0].content == "Hello"
        assert conv.messages[0].role == "user"

    def test_add_multiple_messages(self, store):
        meta = store.create_conversation("Chat")
        store.add_message(meta.conversation_id, Message(role="user", content="Q1", timestamp="t1"))
        store.add_message(meta.conversation_id, Message(role="assistant", content="A1", timestamp="t2"))
        store.add_message(meta.conversation_id, Message(role="user", content="Q2", timestamp="t3"))

        conv = store.get_conversation(meta.conversation_id)
        assert len(conv.messages) == 3

        # Check index updated
        convs = store.list_conversations()
        assert convs[0].message_count == 3

    def test_message_with_metadata(self, store):
        meta = store.create_conversation("Chat")
        msg = Message(
            role="assistant",
            content="Answer text",
            timestamp="t1",
            query_type="document",
            sources=[{"file": "test.pdf", "page": 1}],
            sql="SELECT * FROM t",
        )
        store.add_message(meta.conversation_id, msg)

        conv = store.get_conversation(meta.conversation_id)
        loaded = conv.messages[0]
        assert loaded.query_type == "document"
        assert loaded.sources == [{"file": "test.pdf", "page": 1}]
        assert loaded.sql == "SELECT * FROM t"

    def test_get_recent_messages(self, store):
        meta = store.create_conversation("Chat")
        for i in range(10):
            store.add_message(
                meta.conversation_id,
                Message(role="user", content=f"msg_{i}", timestamp=f"t{i}"),
            )

        recent = store.get_recent_messages(meta.conversation_id, n=3)
        assert len(recent) == 3
        assert recent[0].content == "msg_7"
        assert recent[2].content == "msg_9"

    def test_get_recent_messages_fewer_than_n(self, store):
        meta = store.create_conversation("Chat")
        store.add_message(meta.conversation_id, Message(role="user", content="only", timestamp="t"))
        recent = store.get_recent_messages(meta.conversation_id, n=10)
        assert len(recent) == 1

    def test_add_message_to_nonexistent_conv(self, store):
        # Should not crash
        store.add_message("conv_missing", Message(role="user", content="x", timestamp="t"))


# ── Auto-Title Tests ──────────────────────────────────────


class TestAutoTitle:
    def test_auto_title_short_message(self, store):
        meta = store.create_conversation()
        title = store.auto_title(meta.conversation_id, "Hello world")
        assert title == "Hello world"

    def test_auto_title_long_message_truncated(self, store):
        meta = store.create_conversation()
        long_msg = "A" * 100
        title = store.auto_title(meta.conversation_id, long_msg)
        assert len(title) == 53  # 50 chars + "..."
        assert title.endswith("...")

    def test_auto_title_updates_index(self, store):
        meta = store.create_conversation()
        assert meta.title == "New Chat"
        store.auto_title(meta.conversation_id, "What are the payment terms?")

        convs = store.list_conversations()
        assert convs[0].title == "What are the payment terms?"


# ── Persistence Tests ─────────────────────────────────────


class TestPersistence:
    def test_reload_from_disk(self, tmp_conv_dir):
        # Create store, add data
        store1 = ConversationStore("testuser")
        meta = store1.create_conversation("Persistent Chat")
        store1.add_message(meta.conversation_id, Message(role="user", content="Hello", timestamp="t"))

        # Create new store instance (simulates page refresh)
        store2 = ConversationStore("testuser")
        convs = store2.list_conversations()
        assert len(convs) == 1
        assert convs[0].title == "Persistent Chat"

        conv = store2.get_conversation(meta.conversation_id)
        assert len(conv.messages) == 1
        assert conv.messages[0].content == "Hello"

    def test_per_user_isolation(self, tmp_conv_dir):
        store_a = ConversationStore("alice")
        store_b = ConversationStore("bob")

        store_a.create_conversation("Alice Chat")
        store_b.create_conversation("Bob Chat")

        assert len(store_a.list_conversations()) == 1
        assert len(store_b.list_conversations()) == 1
        assert store_a.list_conversations()[0].title == "Alice Chat"
        assert store_b.list_conversations()[0].title == "Bob Chat"

    def test_json_files_created(self, tmp_conv_dir):
        store = ConversationStore("testuser")
        meta = store.create_conversation("Test")

        user_dir = tmp_conv_dir / "testuser"
        assert (user_dir / "conversations.json").exists()
        assert (user_dir / f"{meta.conversation_id}.json").exists()

    def test_corrupted_index_recovers(self, tmp_conv_dir):
        user_dir = tmp_conv_dir / "testuser"
        user_dir.mkdir(parents=True, exist_ok=True)
        (user_dir / "conversations.json").write_text("NOT VALID JSON")

        store = ConversationStore("testuser")
        assert len(store.list_conversations()) == 0
        # Can still create new conversations
        meta = store.create_conversation("Recovery")
        assert len(store.list_conversations()) == 1


# ── format_chat_context Tests ─────────────────────────────


class TestFormatChatContext:
    def test_empty_messages(self):
        assert format_chat_context([]) == ""

    def test_single_user_message(self):
        msgs = [Message(role="user", content="Hello", timestamp="t")]
        result = format_chat_context(msgs)
        assert "<CONVERSATION_HISTORY>" in result
        assert "User: Hello" in result
        assert "</CONVERSATION_HISTORY>" in result

    def test_user_and_assistant(self):
        msgs = [
            Message(role="user", content="Question?", timestamp="t1"),
            Message(role="assistant", content="Answer.", timestamp="t2"),
        ]
        result = format_chat_context(msgs)
        assert "User: Question?" in result
        assert "Assistant: Answer." in result

    def test_max_messages_limit(self):
        msgs = [
            Message(role="user", content=f"msg_{i}", timestamp=f"t{i}")
            for i in range(20)
        ]
        result = format_chat_context(msgs, max_messages=3)
        # Should only have last 3 messages
        assert "msg_17" in result
        assert "msg_18" in result
        assert "msg_19" in result
        assert "msg_0" not in result

    def test_long_content_truncated(self):
        long_content = "A" * 1000
        msgs = [Message(role="assistant", content=long_content, timestamp="t")]
        result = format_chat_context(msgs)
        # Content should be truncated to 500 chars + "..."
        assert "A" * 500 in result
        assert "A" * 501 not in result

    def test_max_chars_limit(self):
        msgs = [
            Message(role="user", content="X" * 400, timestamp=f"t{i}")
            for i in range(50)
        ]
        result = format_chat_context(msgs, max_messages=50, max_chars=1000)
        # Should stop before exceeding max_chars
        lines = [l for l in result.split("\n") if l.startswith("User:")]
        assert len(lines) < 50

    def test_dual_answers_picks_first(self):
        msgs = [
            Message(
                role="assistant",
                content="",
                timestamp="t",
                dual_answers={
                    "gemini": {"answer": "Gemini says hello"},
                    "openai": {"answer": "OpenAI says hi"},
                },
            ),
        ]
        result = format_chat_context(msgs)
        assert "Gemini says hello" in result


# ── Session Token Tests ───────────────────────────────────


class TestSessionToken:
    def test_create_and_verify(self):
        # Import from app.py
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))

        # Use the functions directly (they're in app.py module scope)
        from app import _create_session_token, _verify_session_token

        token = _create_session_token("admin")
        assert isinstance(token, str)
        parts = token.split(":")
        assert len(parts) == 3
        assert parts[0] == "admin"

        username = _verify_session_token(token)
        assert username == "admin"

    def test_expired_token(self):
        from app import _verify_session_token
        from src.config import SESSION_SECRET

        # Create manually expired token
        expires = int(time.time()) - 100  # expired 100s ago
        payload = f"admin:{expires}"
        import hashlib as hl
        import hmac as hm
        sig = hm.new(SESSION_SECRET.encode(), payload.encode(), hl.sha256).hexdigest()[:16]
        token = f"{payload}:{sig}"

        assert _verify_session_token(token) is None

    def test_tampered_token(self):
        from app import _create_session_token, _verify_session_token

        token = _create_session_token("admin")
        # Tamper with username
        tampered = token.replace("admin", "hacker")
        assert _verify_session_token(tampered) is None

    def test_invalid_format(self):
        from app import _verify_session_token

        assert _verify_session_token("") is None
        assert _verify_session_token("just:two") is None
        assert _verify_session_token("not-a-valid-token") is None
