"""Regression tests for the JSON files destroyed by the old path normalizer.

``src.config.normalize_stored_paths()`` used to rewrite the RAW TEXT of every
JSON file under storage/ and data/ on every process start, turning each
backslash into "/". That broke ``\\"`` into ``/"``, so the string terminated
early and the file stopped parsing. 97 files under storage/ and 11 under data/
were unparseable when this was found — including more than half of one account's
chat history.

The repair is the exact inverse and nothing else: it only ever turns a "/" back
into a "\\", and a result is accepted only when it parses AND is a
length-preserving, slash-only transformation of the input. These tests pin both
halves — that it recovers the real damage, and that it refuses to write when it
cannot prove the result is safe.
"""

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.json_repair import (  # noqa: E402
    BACKUP_SUFFIX, MARKER_NAME, is_slash_only_inverse, repair_file,
    repair_json_text, run_escape_repair_migration,
)


def _corrupt(text: str) -> str:
    """Reproduce exactly what the old normalizer did."""
    text = text.replace("\\\\", "/").replace("\\", "/")
    return re.sub(r"(?<!:)//", "/", text)


# Modelled on a real damaged file: storage/conversations/admin2/conv_0ede68ca.json
HEALTHY_CONVERSATION = {
    "conversation_id": "conv_0ede68ca",
    "title": 'Delay notice for "TIE"',
    "created_at": "2026-05-05T19:43:16.929370",
    "updated_at": "2026-05-05T19:43:25.454244",
    "messages": [
        {"role": "user",
         "content": "Who signed the Infraco contract on behalf of TIE?",
         "timestamp": "t1"},
        {"role": "assistant",
         "content": 'The provided question "behalf of TIE" is incomplete.\n\n'
                    'See\tthe letter.',
         "timestamp": "t2", "query_type": "document"},
    ],
    "document_ids": [],
}


class TestRepairJsonText:
    def test_recovers_the_real_corruption(self):
        original = json.dumps(HEALTHY_CONVERSATION, ensure_ascii=False, indent=2)
        damaged = _corrupt(original)
        with pytest.raises(json.JSONDecodeError):
            json.loads(damaged)                       # the bug, reproduced

        obj, repaired = repair_json_text(damaged)
        assert obj is not None
        assert obj["conversation_id"] == "conv_0ede68ca"
        assert len(obj["messages"]) == 2
        assert '"behalf of TIE"' in obj["messages"][1]["content"]
        assert obj["title"] == 'Delay notice for "TIE"'

    def test_result_is_a_slash_only_inverse(self):
        """The safety invariant: no character is invented, dropped or moved."""
        damaged = _corrupt(json.dumps(HEALTHY_CONVERSATION, ensure_ascii=False, indent=2))
        _, repaired = repair_json_text(damaged)
        assert len(repaired) == len(damaged)
        assert is_slash_only_inverse(damaged, repaired)

    def test_quoted_value_followed_by_a_comma_is_disambiguated(self):
        """The SQL shape: a content quote that looks exactly like a terminator."""
        payload = {"sql": 'SELECT "Date", SUM("Workers") AS n\nFROM t'}
        damaged = _corrupt(json.dumps(payload, ensure_ascii=False, indent=2))
        obj, _ = repair_json_text(damaged)
        assert obj is not None
        assert obj["sql"].startswith('SELECT "Date", SUM("Workers")')

    def test_valid_json_is_returned_unchanged(self):
        text = json.dumps({"a": "b/c"}, indent=2)
        obj, repaired = repair_json_text(text)
        assert repaired == text and obj == {"a": "b/c"}

    def test_unrelated_garbage_is_refused(self):
        assert repair_json_text("{ this was never json") == (None, None)

    def test_truncated_file_is_refused(self):
        text = json.dumps(HEALTHY_CONVERSATION, indent=2)[:200]
        assert repair_json_text(_corrupt(text)) == (None, None)

    def test_content_escapes_restore_newlines_but_spare_paths(self):
        """Phase B: /n becomes a newline, but a real path keeps its slashes."""
        payload = {"content": "line one\nline two",
                   "note": "see /app/data/tables/Manpower.xlsx"}
        damaged = _corrupt(json.dumps(payload, ensure_ascii=False, indent=2))
        obj, _ = repair_json_text(damaged, restore_content_escapes=True)
        assert obj["content"] == "line one\nline two"
        assert obj["note"] == "see /app/data/tables/Manpower.xlsx"


class TestRepairFile:
    def test_healthy_file_is_left_byte_identical(self, tmp_path):
        p = tmp_path / "conv_ok.json"
        p.write_text(json.dumps(HEALTHY_CONVERSATION, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        before = p.read_bytes()

        assert repair_file(p) == "ok"
        assert p.read_bytes() == before
        assert not p.with_name(p.name + BACKUP_SUFFIX).exists()

    def test_damaged_file_is_repaired_and_the_original_kept(self, tmp_path):
        p = tmp_path / "conversations" / "u" / "conv_x.json"
        p.parent.mkdir(parents=True)
        damaged = _corrupt(json.dumps(HEALTHY_CONVERSATION, ensure_ascii=False, indent=2))
        p.write_text(damaged, encoding="utf-8")

        assert repair_file(p) == "repaired"
        assert json.loads(p.read_text(encoding="utf-8"))["conversation_id"] == "conv_0ede68ca"
        # nothing is ever made worse — the input is kept verbatim
        assert p.with_name(p.name + BACKUP_SUFFIX).read_text(encoding="utf-8") == damaged

    def test_unrepairable_file_is_left_untouched_and_unbacked(self, tmp_path):
        p = tmp_path / "junk.json"
        p.write_text("{ not json at all", encoding="utf-8")
        assert repair_file(p) == "unrepairable"
        assert p.read_text(encoding="utf-8") == "{ not json at all"
        assert not p.with_name(p.name + BACKUP_SUFFIX).exists()

    def test_repair_is_idempotent(self, tmp_path):
        p = tmp_path / "conversations" / "u" / "conv_x.json"
        p.parent.mkdir(parents=True)
        p.write_text(_corrupt(json.dumps(HEALTHY_CONVERSATION, ensure_ascii=False, indent=2)),
                     encoding="utf-8")
        assert repair_file(p) == "repaired"
        first = p.read_bytes()
        assert repair_file(p) == "ok"
        assert p.read_bytes() == first


class TestMigration:
    def test_runs_once_and_writes_a_marker(self, tmp_path):
        root = tmp_path / "storage" / "conversations" / "u"
        root.mkdir(parents=True)
        (root / "conv_a.json").write_text(
            _corrupt(json.dumps(HEALTHY_CONVERSATION, ensure_ascii=False, indent=2)),
            encoding="utf-8")

        result = run_escape_repair_migration(
            roots=(tmp_path / "storage",), marker_dir=tmp_path / "storage")
        assert result["repaired"] == 1
        assert (tmp_path / "storage" / MARKER_NAME).exists()

        # A second boot is a no-op.
        assert run_escape_repair_migration(
            roots=(tmp_path / "storage",), marker_dir=tmp_path / "storage") is None

    def test_backups_are_not_re_scanned(self, tmp_path):
        root = tmp_path / "storage"
        root.mkdir()
        (root / f"x.json{BACKUP_SUFFIX}").write_text("{ broken", encoding="utf-8")
        result = run_escape_repair_migration(roots=(root,), marker_dir=root)
        assert result["unrepairable"] == 0
