"""Document-selection memory — project-scoped, confirmation-gated."""

import pytest

import src.learning.document_memory as dm


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(dm, "_STORE", tmp_path / "document_memory.json")
    yield


def test_analysis_key_stable():
    assert dm.analysis_key("dcma_latest", "Delayed Blockwork") == \
        "dcma_latest:delayed-blockwork"
    assert dm.analysis_key("programme_inventory") == "programme_inventory"


def test_not_approved_is_never_suggested():
    dm.record_selection("k", ["d1", "d2"], corpus="p1", approved=False)
    assert dm.suggest("k", corpus="p1") is None          # safety: no silent reuse


def test_confirm_then_suggest():
    dm.confirm_selection("k", ["d1", "d2"], corpus="p1")
    s = dm.suggest("k", corpus="p1")
    assert s and s["doc_ids"] == ["d1", "d2"] and s["approved"] is True


def test_project_scoped_isolation():
    dm.confirm_selection("k", ["d1"], corpus="p1")
    assert dm.suggest("k", corpus="p1") is not None
    assert dm.suggest("k", corpus="p2") is None          # different project
    assert dm.suggest("k", project_id="proj-9") is None


def test_record_rejects_empty_and_never_raises():
    assert dm.record_selection("", [], corpus="p1")["ok"] is False
    assert dm.suggest("missing", corpus="p1") is None
