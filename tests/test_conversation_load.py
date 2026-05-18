"""Regression tests for the conversation-reload bug (Bug 1).

Symptom: clicking an old chat opens the "new chat" welcome screen because
the JSON on disk has an empty ``messages`` array even when its index claims
``message_count > 0``. These tests pin down the persistence-side behaviour
that fuels that frontend symptom.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.conversation_store import ConversationStore, Conversation, Message  # noqa: E402
import src.conversation_store as csmod  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Fresh ConversationStore rooted at a temp dir."""
    monkeypatch.setattr(csmod, "CONVERSATIONS_DIR", tmp_path)
    return ConversationStore("tester")


def _write_conv_file(store: ConversationStore, conv_id: str, payload: dict) -> Path:
    path = store._conv_path(conv_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class TestLoadConversation:
    def test_loads_messages_when_present(self, store):
        _write_conv_file(store, "conv_ok", {
            "conversation_id": "conv_ok",
            "title": "Chat",
            "created_at": "2026-05-01T00:00:00",
            "updated_at": "2026-05-01T00:00:00",
            "message_count": 1,
            "messages": [{"role": "user", "content": "hi", "timestamp": "t"}],
            "document_ids": [],
        })
        conv = store._load_conversation("conv_ok")
        assert conv is not None
        assert len(conv.messages) == 1
        assert conv.messages[0].content == "hi"

    def test_empty_messages_returns_conversation_with_no_messages(self, store):
        """The bug: file has 'messages': [] but count claims otherwise.
        Loader must still return a valid Conversation (frontend handles it)."""
        _write_conv_file(store, "conv_empty", {
            "conversation_id": "conv_empty",
            "title": "Empty body",
            "created_at": "2026-05-01T00:00:00",
            "updated_at": "2026-05-01T00:00:00",
            "message_count": 5,
            "messages": [],
        })
        conv = store._load_conversation("conv_empty")
        assert conv is not None
        assert conv.messages == []
        assert conv.title == "Empty body"

    def test_empty_messages_with_nonzero_count_logs_warning(
        self, store, caplog
    ):
        _write_conv_file(store, "conv_drift", {
            "conversation_id": "conv_drift",
            "title": "Drift",
            "created_at": "2026-05-01T00:00:00",
            "updated_at": "2026-05-01T00:00:00",
            "message_count": 3,
            "messages": [],
        })
        with caplog.at_level(logging.WARNING):
            store._load_conversation("conv_drift")
        assert any(
            "empty messages array" in rec.message
            and "conv_drift" in rec.message
            for rec in caplog.records
        ), f"warning not emitted: {[r.message for r in caplog.records]}"

    def test_empty_messages_with_zero_count_does_not_warn(
        self, store, caplog
    ):
        """A brand-new conversation legitimately has no messages yet."""
        _write_conv_file(store, "conv_new", {
            "conversation_id": "conv_new",
            "title": "Fresh",
            "created_at": "2026-05-01T00:00:00",
            "updated_at": "2026-05-01T00:00:00",
            "message_count": 0,
            "messages": [],
        })
        with caplog.at_level(logging.WARNING):
            store._load_conversation("conv_new")
        assert not any(
            "empty messages array" in r.message for r in caplog.records
        )

    def test_missing_messages_field_defaults_to_empty(self, store):
        _write_conv_file(store, "conv_missing", {
            "conversation_id": "conv_missing",
            "title": "Missing field",
            "created_at": "2026-05-01T00:00:00",
            "updated_at": "2026-05-01T00:00:00",
            "message_count": 0,
            # no 'messages' key at all
        })
        conv = store._load_conversation("conv_missing")
        assert conv is not None
        assert conv.messages == []

    def test_unknown_file_returns_none(self, store):
        assert store._load_conversation("does_not_exist") is None


class TestRolePreservation:
    def test_roles_round_trip(self, store):
        conv = Conversation(
            conversation_id="conv_rt",
            title="rt",
            created_at="t",
            updated_at="t",
            messages=[
                Message(role="user", content="hi", timestamp="t1"),
                Message(role="assistant", content="hello", timestamp="t2"),
            ],
        )
        # Persist via the store, then reload
        store._save_conversation(conv)
        loaded = store._load_conversation("conv_rt")
        assert loaded is not None
        assert [m.role for m in loaded.messages] == ["user", "assistant"]
