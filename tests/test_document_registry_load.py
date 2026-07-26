"""Regression tests for the document-registry forward-compatibility bug.

Symptom: the whole document library shows up empty after running a build older
than the one that wrote ``storage/document_registry.json``. A registry written
by a newer build carries fields this ``DocumentRecord`` never declared, and
``DocumentRecord(**rec)`` raised on the first one — inside the load loop, so
every record after it was lost too, and the next save persisted the truncated
set.

Concretely: rolling back past the XER-upload work left 235 records all carrying
``programme_meta``, the first of them at index 0, so the library loaded as zero
documents.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import src.document_registry as regmod  # noqa: E402
from src.document_registry import DocumentRecord, DocumentRegistry  # noqa: E402


def _base_record(doc_id: str) -> dict:
    return {
        "doc_id": doc_id,
        "file_name": f"{doc_id}.pdf",
        "file_path": f"/tmp/{doc_id}.pdf",
        "file_size_kb": 10,
        "file_type": "document",
        "extension": ".pdf",
    }


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """Fresh DocumentRegistry rooted at a temp file.

    DocumentRegistry is a singleton, so the cached instance has to go or the
    fixture would hand back whatever the previous test loaded.
    """
    monkeypatch.setattr(regmod, "REGISTRY_FILE", tmp_path / "document_registry.json")
    monkeypatch.setattr(DocumentRegistry, "_instance", None)

    def _make(payload: dict) -> DocumentRegistry:
        regmod.REGISTRY_FILE.write_text(json.dumps(payload), encoding="utf-8")
        DocumentRegistry._instance = None
        return DocumentRegistry()

    return _make


class TestLoadForwardCompatibility:
    def test_unknown_field_does_not_empty_the_library(self, registry):
        """The exact rollback shape: every record carries an unknown field."""
        payload = {
            f"doc{i}": {**_base_record(f"doc{i}"), "programme_meta": {"rev": "A"}}
            for i in range(5)
        }
        reg = registry(payload)
        assert len(reg._records) == 5

    def test_unknown_field_on_the_first_record_keeps_the_rest(self, registry):
        """The old loop aborted on the first bad record, losing all the others."""
        payload = {
            "doc0": {**_base_record("doc0"), "programme_meta": {"rev": "A"}},
            "doc1": _base_record("doc1"),
            "doc2": _base_record("doc2"),
        }
        reg = registry(payload)
        assert set(reg._records) == {"doc0", "doc1", "doc2"}

    def test_unknown_field_is_dropped_not_stored(self, registry):
        reg = registry({"doc0": {**_base_record("doc0"), "programme_meta": {"rev": "A"}}})
        assert not hasattr(reg._records["doc0"], "programme_meta")

    def test_known_fields_survive_alongside_unknown_ones(self, registry):
        reg = registry({
            "doc0": {
                **_base_record("doc0"),
                "programme_meta": {"rev": "A"},
                "status": "completed",
                "llm_topics": ["delay", "eot"],
            }
        })
        rec = reg._records["doc0"]
        assert rec.status == "completed"
        assert rec.llm_topics == ["delay", "eot"]

    def test_missing_optional_fields_fall_back_to_defaults(self, registry):
        reg = registry({"doc0": _base_record("doc0")})
        rec = reg._records["doc0"]
        assert rec.status == "processing"
        assert rec.table_names == []
        assert rec.data_tables_count == 0


class TestLoadResilience:
    def test_one_malformed_record_costs_only_itself(self, registry):
        """A record missing a required field must not take the others down."""
        payload = {
            "doc0": _base_record("doc0"),
            "broken": {"doc_id": "broken"},          # no file_name/path/size/type
            "doc2": _base_record("doc2"),
        }
        reg = registry(payload)
        assert set(reg._records) == {"doc0", "doc2"}

    def test_unreadable_file_leaves_an_empty_registry(self, registry, tmp_path):
        regmod.REGISTRY_FILE.write_text("{not json", encoding="utf-8")
        DocumentRegistry._instance = None
        assert DocumentRegistry()._records == {}

    def test_absent_file_leaves_an_empty_registry(self, tmp_path, monkeypatch):
        monkeypatch.setattr(regmod, "REGISTRY_FILE", tmp_path / "missing.json")
        monkeypatch.setattr(DocumentRegistry, "_instance", None)
        assert DocumentRegistry()._records == {}


class TestSaveRoundTrip:
    def test_reload_after_save_keeps_every_record(self, registry):
        """The dangerous half of the bug: a truncated load then overwrote disk."""
        payload = {
            f"doc{i}": {**_base_record(f"doc{i}"), "programme_meta": {"rev": "A"}}
            for i in range(4)
        }
        reg = registry(payload)
        reg._save()

        DocumentRegistry._instance = None
        assert len(DocumentRegistry()._records) == 4

    def test_save_drops_the_unknown_field_from_disk(self, registry):
        reg = registry({"doc0": {**_base_record("doc0"), "programme_meta": {"rev": "A"}}})
        reg._save()
        on_disk = json.loads(regmod.REGISTRY_FILE.read_text(encoding="utf-8"))
        assert "programme_meta" not in on_disk["doc0"]
        assert on_disk["doc0"]["file_name"] == "doc0.pdf"


def test_record_from_dict_ignores_unknown_keys_directly():
    rec = DocumentRegistry._record_from_dict({
        **_base_record("doc0"), "programme_meta": {}, "some_future_field": 1,
    })
    assert isinstance(rec, DocumentRecord)
    assert rec.doc_id == "doc0"
