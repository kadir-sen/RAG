"""The path normalizer must never again be able to break a JSON file.

The old one worked on raw text and applied ``raw.replace("\\", "/")`` to every
JSON file under storage/ and data/, at import time, on every process start. That
destroyed the escapes JSON is built on — ``\\"`` became ``/"`` and the file
stopped parsing — and it swept ``storage/conversations/**`` too, which is user
prose holding no path this application owns. 97 files under storage/ and 11
under data/ were unparseable when it was found.

The replacement parses the document and rewrites only string *values* that are
Windows absolute paths, under path-bearing keys, in a fixed list of registry
files. Structural corruption is impossible by construction.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.config as cfg  # noqa: E402


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "BASE_DIR", tmp_path)
    monkeypatch.setattr(cfg, "STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setattr(cfg, "CONVERTER_REGISTRY_FILE",
                        tmp_path / "storage" / "converters" / "registry.json")
    (tmp_path / "storage" / "parquet").mkdir(parents=True)
    (tmp_path / "storage" / "converters").mkdir(parents=True)
    return tmp_path


class TestConversationsAreNeverTouched:
    def test_a_conversation_file_is_left_byte_identical(self, sandbox):
        """The whole bug, in one assertion."""
        conv_dir = sandbox / "storage" / "conversations" / "admin2"
        conv_dir.mkdir(parents=True)
        p = conv_dir / "conv_0ede68ca.json"
        payload = {
            "conversation_id": "conv_0ede68ca",
            "title": 'Delay notice for "TIE"',
            "messages": [{"role": "assistant",
                          "content": 'The question "behalf of TIE" is '
                                     'incomplete.\n\nSee\tthe letter.',
                          "timestamp": "t"}],
        }
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        before = p.read_bytes()

        cfg.normalize_stored_paths()

        assert p.read_bytes() == before
        assert json.loads(p.read_text(encoding="utf-8")) == payload


class TestRegistryPathsAreStillNormalized:
    def test_windows_absolute_path_is_mapped_onto_the_app_root(self, sandbox):
        reg = sandbox / "storage" / "document_registry.json"
        reg.write_text(json.dumps({
            "doc0": {"doc_id": "doc0", "file_name": "a.pdf",
                     "file_path": r"C:\projects\ML_project\data\documents\a.pdf"},
        }, indent=2), encoding="utf-8")

        assert cfg.normalize_stored_paths() == 1
        rec = json.loads(reg.read_text(encoding="utf-8"))["doc0"]
        assert rec["file_path"] == f"{sandbox}/data/documents/a.pdf"

    def test_posix_paths_are_a_no_op(self, sandbox):
        reg = sandbox / "storage" / "document_registry.json"
        payload = {"doc0": {"file_path": "/app/data/documents/a.pdf"}}
        reg.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        before = reg.read_bytes()

        assert cfg.normalize_stored_paths() == 0
        assert reg.read_bytes() == before

    def test_prose_that_merely_mentions_a_windows_path_is_untouched(self, sandbox):
        """Only path-bearing KEYS are rewritten — a quoted path inside text is
        content, and the old version mangled exactly this."""
        reg = sandbox / "storage" / "document_registry.json"
        payload = {"doc0": {"llm_summary": r"The letter cites C:\projects\ML_project\x."}}
        reg.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        assert cfg.normalize_stored_paths() == 0
        assert json.loads(reg.read_text(encoding="utf-8")) == payload

    def test_an_unparseable_registry_is_skipped_not_rewritten(self, sandbox):
        reg = sandbox / "storage" / "document_registry.json"
        reg.write_text("{ broken", encoding="utf-8")

        assert cfg.normalize_stored_paths() == 0
        assert reg.read_text(encoding="utf-8") == "{ broken"


def test_it_does_not_run_at_import_by_default():
    """It used to run unconditionally at import time, which is what made a
    read-only startup destructive."""
    assert cfg.NORMALIZE_STORED_PATHS is False
