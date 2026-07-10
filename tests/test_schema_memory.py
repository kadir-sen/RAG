"""Schema memory — suggest / confirm / reuse cycle (the learning north star)."""

import pytest

import src.schema_profiler as sp
from src.learning import schema_memory as sm


@pytest.fixture()
def isolated_mappings(tmp_path, monkeypatch):
    """Point the profiler's persisted-mapping store at a temp file and rebuild
    the singleton, so confirmations don't touch the real storage/."""
    monkeypatch.setattr(sp, "_MAPPINGS_FILE", tmp_path / "schema_mappings.json")
    monkeypatch.setattr(sp, "_PROFILER", None)
    yield
    monkeypatch.setattr(sp, "_PROFILER", None)


def test_suggest_is_deterministic_and_never_raises():
    s = sm.suggest_for_columns(["Machinery Name", "Estimated Machinery Hours",
                                "Date", "Block"])
    assert s["schema_id"] == "equipment_log"
    assert s["status"] in ("confident", "needs_confirmation")
    assert isinstance(sm.suggest_for_columns([]), dict)          # no crash
    assert sm.suggest_for_columns(None)["status"] == "raw_only"


def test_junk_headers_are_raw_only_not_silently_assigned():
    s = sm.suggest_for_columns(["col_0", "unnamed", "x"])
    assert s["schema_id"] is None
    assert s["status"] == "raw_only"


def test_confirm_then_reuse_cycle(isolated_mappings):
    cols = ["Machinery Name", "Estimated Machinery Hours", "Date", "Block"]
    assert sm.suggest_for_columns(cols)["source"] == "computed"
    res = sm.confirm_schema_mapping(cols, "equipment_log")
    assert res["ok"] and res["schema_id"] == "equipment_log"

    after = sm.suggest_for_columns(cols)
    assert after["source"] == "persisted"
    assert after["schema_id"] == "equipment_log"
    assert after["status"] == "confident"
    assert sm.is_confirmed(cols) is True


def test_confirm_persists_across_singleton_rebuild(isolated_mappings, monkeypatch):
    cols = ["Job Description", "Number of Workers", "Quantification",
            "Unit of Measure", "Activity Description"]
    sm.confirm_schema_mapping(cols, "manpower_production")
    # Rebuild the profiler singleton → must reload from disk, still confirmed.
    monkeypatch.setattr(sp, "_PROFILER", None)
    assert sm.is_confirmed(cols) is True
    assert sm.suggest_for_columns(cols)["schema_id"] == "manpower_production"


def test_confirm_rejects_incomplete_input(isolated_mappings):
    assert sm.confirm_schema_mapping([], "equipment_log")["ok"] is False
    assert sm.confirm_schema_mapping(["a"], "")["ok"] is False


def test_confirm_column_never_raises_on_garbage():
    assert sm.confirm_column("", "", "")["ok"] is False


def test_pending_confirmations_returns_list():
    assert isinstance(sm.pending_confirmations(), list)
