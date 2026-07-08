"""Adapter + executor + registry-matching tests. No LLM, no network."""

import json
from pathlib import Path

import pytest

from src.programme_tools import match_query, run_tool
from src.programme_tools.adapters import (
    dcma_adapter, inventory_adapter, milestone_adapter,
)
from src.programme_tools.guards import computation_guard
from src.programme_tools.schemas import ToolResult

FIXTURES = Path(__file__).parent / "fixtures" / "xer"


def _records(n=3):
    paths = sorted(FIXTURES.glob("*.xer"))[:n]
    return [{"file_name": p.name, "file_path": str(p), "doc_id": p.stem,
             "status": "completed"} for p in paths]


@pytest.fixture(autouse=True)
def artifacts_tmp(tmp_path, monkeypatch):
    import src.programme_tools.config_paths as cp
    monkeypatch.setattr(cp, "artifacts_dir", lambda: tmp_path)
    yield tmp_path


# ── adapters ─────────────────────────────────────────────────
class TestInventoryAdapter:
    def test_result_shape(self):
        result, blobs = inventory_adapter.run(_records())
        assert result.status == "complete"
        assert json.dumps(result.to_dict())  # JSON round-trip
        table = result.tables[0]
        assert len(table["rows"]) == 3
        roles = [row[-1] for row in table["rows"]]
        assert "baseline" in roles and "current" in roles
        assert blobs and blobs[0].data[:2] == b"PK"
        assert "baseline=" in result.summary

    def test_dates_are_iso_strings(self):
        result, _ = inventory_adapter.run(_records())
        raw = json.dumps(result.to_dict()["raw"])
        assert "T00:00:00" in raw or '"20' in raw  # ISO datetimes, no datetime objs


class TestDcmaAdapter:
    def test_fourteen_rows(self):
        result, blobs = dcma_adapter.run(_records(1))
        assert len(result.tables[0]["rows"]) == 14
        assert result.status == "complete"
        assert "pass" in result.summary and "fail" in result.summary
        assert blobs[0].filename.startswith("dcma_scorecard_")
        assert result.caveats  # screening caveat always present


class TestMilestoneAdapter:
    def test_shift_and_confirmation_flags(self):
        result, blobs = milestone_adapter.run(_records())
        assert json.dumps(result.to_dict())
        summary_table = result.tables[0]
        keys = [r[0] for r in summary_table["rows"]]
        assert "MS1000" in keys
        # chart series follow the top-N-by-abs-shift rule and carry ISO x values
        if result.charts:
            pt = result.charts[0]["series"][0]["points"][0]
            assert isinstance(pt["x"], str) and pt["x"][:2] == "20"
        # as-recorded caveat always present
        assert any("not independently verified" in c for c in result.caveats)

    def test_requires_two_files_enforced_by_registry_not_adapter(self):
        # adapter itself runs on 1 file (engine tolerates it); the handler
        # enforces min_xer_files via the registry spec.
        from src.programme_tools.registry import REGISTRY
        assert REGISTRY["programme.milestone_shift"].min_xer_files == 2


# ── executor + computation guard ─────────────────────────────
class TestExecutor:
    def test_unknown_tool_refused(self):
        result = run_tool("run_delay_analysis", _records())
        assert result.status == "failed"
        assert "Unknown programme tool" in result.summary

    def test_happy_path_writes_artifacts(self, artifacts_tmp):
        result = run_tool("programme.dcma_14_point", _records(1), run_id="testrun")
        assert result.status == "complete"
        assert result.artifacts and result.artifacts[0]["url"].startswith(
            "/api/artifacts/testrun/")
        written = artifacts_tmp / "testrun" / result.artifacts[0]["filename"]
        assert written.exists() and written.read_bytes()[:2] == b"PK"

    def test_missing_file_fails_cleanly(self):
        recs = [{"file_name": "ghost.xer", "file_path": "/nope/ghost.xer",
                 "status": "completed"}]
        result = run_tool("programme.inventory", recs)
        assert result.status == "failed"
        assert "missing on disk" in result.summary

    def test_non_xer_extension_fails(self):
        recs = [{"file_name": "letter.pdf", "file_path": "/tmp/x.pdf",
                 "status": "completed"}]
        result = run_tool("programme.dcma_14_point", recs)
        assert result.status == "failed"
        assert "not a .xer" in result.summary

    def test_corrupt_xer_fails_cleanly(self, tmp_path):
        bad = tmp_path / "bad.xer"
        bad.write_text("this is not an xer file at all")
        result = run_tool("programme.inventory", [
            {"file_name": "bad.xer", "file_path": str(bad), "status": "completed"}])
        assert result.status == "failed"
        assert "valid P6 XER" in result.summary or "could not be parsed" in result.summary


class TestComputationGuardPost:
    def test_complete_without_tables_downgraded(self):
        r = ToolResult(tool_id="programme.inventory", status="complete",
                       summary="ok", tables=[], warnings=[])
        out = computation_guard.validate_result(r)
        assert out.status == "partial"
        assert out.requires_analyst_review is True

    def test_unconfirmed_matches_force_analyst_flag(self):
        r = ToolResult(tool_id="programme.milestone_shift", status="complete",
                       summary="ok", tables=[{"title": "t", "columns": [], "rows": []}],
                       raw={"needs_confirmation": [{"task_code": "X"}]},
                       requires_analyst_review=False)
        out = computation_guard.validate_result(r)
        assert out.requires_analyst_review is True


# ── registry matching (user's §11 routing cases) ─────────────
class TestRegistryMatching:
    @pytest.mark.parametrize("q,expected", [
        ("Run DCMA check on this XER", "programme.dcma_14_point"),
        ("run a schedule health check", "programme.dcma_14_point"),
        ("Show me milestone movements", "programme.milestone_shift"),
        ("how did the completion milestones shift?", "programme.milestone_shift"),
        ("programme inventory please", "programme.inventory"),
        ("which XER revisions are loaded?", "programme.inventory"),
    ])
    def test_positive_routing(self, q, expected):
        m = match_query(q)
        assert m and m["kind"] == "tool" and m["id"] == expected

    @pytest.mark.parametrize("q", [
        "Create delay event chronology from letters",
        "Who caused the delay?",
        "is the EOT claim time-barred?",
        "summarise the correspondence about milestones",
        "draft a notice about the schedule health",
        "what does the contract say about delay penalties?",
    ])
    def test_negative_routing(self, q):
        assert match_query(q) is None

    def test_workflow_trigger(self):
        m = match_query("Generate preliminary programme analysis report")
        assert m and m["kind"] == "workflow"

    def test_workflow_beats_single_tool(self):
        m = match_query("prelim schedule analysis pack with dcma")
        assert m and m["kind"] == "workflow"
