"""Chat history must survive a damaged file, a damaged index, and an empty mount.

Three loss paths, all live in production before this change:

  * **Opening a chat deleted it.** A file the old path normalizer had corrupted
    failed to load, the API called ``drop_ghost_entry``, and the entry left the
    index — while the file stayed on disk, unreachable, because nothing in the
    UI can reach an id that is not in the index. Reproduced against production:
    a list of 7 became 6 by clicking one of them.
  * **A corrupt index emptied everything.** ``_load_index`` blanked the whole
    list on any exception and ``_save_index`` rewrites the file in full, so the
    next "New Chat" delisted every prior conversation. One quoted character in a
    title was enough. This is the shape ``src/document_registry.py`` already
    fixed.
  * **An unmounted volume would prune the lot.** ``_prune_index`` drops entries
    whose file is missing — which, if ``./storage`` ever failed to mount, is all
    of them, on the first request.
"""

import json
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.config as cfg  # noqa: E402
from src.conversation_store import ConversationStore  # noqa: E402


@pytest.fixture
def store_factory(tmp_path, monkeypatch):
    """A ConversationStore rooted in a temp dir, plus helpers to seed it."""
    conv_root = tmp_path / "conversations"
    monkeypatch.setattr(cfg, "CONVERSATIONS_DIR", conv_root)
    import src.conversation_store as cs
    monkeypatch.setattr(cs, "CONVERSATIONS_DIR", conv_root)

    def make(username="u"):
        return ConversationStore(username)

    def seed_file(username, conv_id, *, messages=1, text="hello", broken=False):
        d = conv_root / username
        d.mkdir(parents=True, exist_ok=True)
        payload = {
            "conversation_id": conv_id,
            "title": f"Title {conv_id}",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "messages": [{"role": "user", "content": text, "timestamp": "t"}
                         for _ in range(messages)],
            "document_ids": [],
        }
        raw = json.dumps(payload, ensure_ascii=False, indent=2)
        if broken:
            raw = raw.replace("\\", "/")          # exactly what the normalizer did
        (d / f"{conv_id}.json").write_text(raw, encoding="utf-8")

    def seed_index(username, entries):
        d = conv_root / username
        d.mkdir(parents=True, exist_ok=True)
        (d / "conversations.json").write_text(
            json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")

    make.seed_file = seed_file
    make.seed_index = seed_index
    make.root = conv_root
    return make


def _entry(conv_id, **kw):
    base = {"conversation_id": conv_id, "title": f"Title {conv_id}",
            "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
            "message_count": 1, "pinned": False, "archived": False}
    base.update(kw)
    return base


class TestOpeningAChatMustNotDeleteIt:
    def test_corrupt_but_present_file_keeps_its_index_entry(self, store_factory):
        """The exact production failure, as a unit test."""
        store_factory.seed_file("u", "conv_a", text='he said "hi"', broken=True)
        store_factory.seed_index("u", [_entry("conv_a")])
        store = store_factory("u")
        assert len(store._index) == 1

        store.drop_ghost_entry("conv_a")          # what the 404 handler calls

        assert [m.conversation_id for m in store._index] == ["conv_a"]
        assert json.loads((store_factory.root / "u" / "conversations.json")
                          .read_text(encoding="utf-8"))

    def test_a_genuinely_missing_file_is_still_pruned(self, store_factory):
        store_factory.seed_file("u", "conv_a")
        store_factory.seed_index("u", [_entry("conv_a"), _entry("conv_gone")])
        store = store_factory("u")

        store.drop_ghost_entry("conv_gone")

        assert [m.conversation_id for m in store._index] == ["conv_a"]

    def test_a_corrupt_conversation_is_repaired_on_read(self, store_factory):
        store_factory.seed_file("u", "conv_a", text='he said "hi"', broken=True)
        store_factory.seed_index("u", [_entry("conv_a")])
        store = store_factory("u")

        conv = store.get_conversation("conv_a")

        assert conv is not None
        assert conv.messages[0].content == 'he said "hi"'


class TestACorruptIndexMustNotEmptyTheStore:
    def test_unparseable_index_is_repaired_not_blanked(self, store_factory):
        store_factory.seed_file("u", "conv_a")
        raw = json.dumps([_entry("conv_a", title='Delay for "TIE"')],
                         ensure_ascii=False, indent=2).replace("\\", "/")
        (store_factory.root / "u").mkdir(parents=True, exist_ok=True)
        (store_factory.root / "u" / "conversations.json").write_text(raw, encoding="utf-8")

        store = store_factory("u")

        assert [m.conversation_id for m in store._index] == ["conv_a"]
        assert store._index[0].title == 'Delay for "TIE"'

    def test_unrepairable_index_is_rebuilt_from_the_files(self, store_factory):
        store_factory.seed_file("u", "conv_a")
        store_factory.seed_file("u", "conv_b")
        (store_factory.root / "u" / "conversations.json").write_text(
            "{ not json at all", encoding="utf-8")

        store = store_factory("u")

        assert sorted(m.conversation_id for m in store._index) == ["conv_a", "conv_b"]

    def test_one_bad_record_costs_one_conversation_not_all_of_them(self, store_factory):
        store_factory.seed_file("u", "conv_a")
        store_factory.seed_file("u", "conv_b")
        store_factory.seed_index("u", [_entry("conv_a"), {"title": "no id here"},
                                       _entry("conv_b")])

        store = store_factory("u")

        assert sorted(m.conversation_id for m in store._index) == ["conv_a", "conv_b"]

    def test_an_unreadable_index_refuses_to_be_written_over(self, store_factory,
                                                            monkeypatch):
        """A read error must never become a truncating write."""
        store_factory.seed_file("u", "conv_a")
        store_factory.seed_index("u", [_entry("conv_a")])
        index_path = store_factory.root / "u" / "conversations.json"
        before = index_path.read_text(encoding="utf-8")

        import src.conversation_store as cs

        def _boom(self, *a, **k):
            raise OSError("disk went away")

        monkeypatch.setattr(cs.Path, "read_text", _boom, raising=False)
        store = store_factory("u")
        monkeypatch.undo()

        assert store._index_loaded is False
        store._save_index()                       # must be refused
        assert index_path.read_text(encoding="utf-8") == before


class TestAnUnmountedVolumeMustNotPruneEverything:
    def test_prune_is_refused_when_no_conversation_files_exist(self, store_factory):
        store_factory.seed_index("u", [_entry("conv_a"), _entry("conv_b")])
        # no conv_*.json at all — the shape of a storage volume that didn't mount
        store = store_factory("u")

        assert sorted(m.conversation_id for m in store._index) == ["conv_a", "conv_b"]
        assert len(json.loads((store_factory.root / "u" / "conversations.json")
                              .read_text(encoding="utf-8"))) == 2


class TestOrphanAdoption:
    def test_files_with_messages_are_relisted(self, store_factory):
        store_factory.seed_file("u", "conv_a")
        store_factory.seed_file("u", "conv_orphan", messages=3)
        store_factory.seed_index("u", [_entry("conv_a")])
        store = store_factory("u")

        assert store.adopt_orphans() == 1
        assert "conv_orphan" in [m.conversation_id for m in store._index]

    def test_empty_shells_are_left_alone(self, store_factory):
        """179 of 181 orphans on the real corpus are empty "New Chat" shells;
        re-listing those would bury the real history under empty rows."""
        store_factory.seed_file("u", "conv_a")
        store_factory.seed_file("u", "conv_empty", messages=0)
        store_factory.seed_index("u", [_entry("conv_a")])
        store = store_factory("u")

        assert store.adopt_orphans() == 0
        assert [m.conversation_id for m in store._index] == ["conv_a"]

    def test_adoption_is_idempotent(self, store_factory):
        store_factory.seed_file("u", "conv_orphan", messages=2)
        store_factory.seed_index("u", [])
        store = store_factory("u")

        assert store.adopt_orphans() == 1
        assert store.adopt_orphans() == 0
