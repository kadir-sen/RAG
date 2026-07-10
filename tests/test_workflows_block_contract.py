"""Workflow outputs only ever use supported block types."""

from pathlib import Path
from unittest.mock import patch

import pytest

from backend.models.blocks import validate_blocks
from src.router import QueryRouter
from src.workflows import plan, run_workflow
from src.workflows.types import WorkflowId

FIXTURES = Path(__file__).parent / "fixtures" / "xer"


def _records(n=3):
    paths = sorted(FIXTURES.glob("*.xer"))[:n]
    return [{"doc_id": p.stem, "file_name": p.name, "file_path": str(p),
             "status": "completed"} for p in paths]


def _stub_router(records=None):
    r = QueryRouter.__new__(QueryRouter)
    recs = records if records is not None else _records()
    r._programme_records = lambda doc_ids=None: recs
    return r


@pytest.fixture(autouse=True)
def artifacts_tmp(tmp_path, monkeypatch):
    import src.programme_tools.config_paths as cp
    monkeypatch.setattr(cp, "artifacts_dir", lambda: tmp_path)
    yield


def _run(q, router):
    return run_workflow(plan(q.lower()), q, router)


def test_planned_blocks_pass_contract_without_clarification():
    wr = _run("create notice compliance matrix", _stub_router())
    kept, dropped = validate_blocks(wr.blocks)
    assert dropped == []
    assert "clarification" not in [b["type"] for b in kept]


def test_inventory_blocks_pass_contract():
    wr = _run("what programme files are available", _stub_router())
    kept, dropped = validate_blocks(wr.blocks)
    assert dropped == []
    types = {b["type"] for b in kept}
    assert types <= {"markdown_text", "data_table", "chart",
                     "html_report_section", "artifact_link", "caveats",
                     "validation_status", "clarification"}


def test_milestone_blocks_pass_contract():
    with patch("src.programme_tools.narrative.compose_narrative",
               side_effect=lambda res, ctx=None, use_llm=True: res.summary):
        wr = _run("show milestone movements as a chart", _stub_router())
    kept, dropped = validate_blocks(wr.blocks)
    assert dropped == []
    assert any(b["type"] == "validation_status" for b in kept)


def test_input_resolution_summary_renders_as_markdown():
    with patch("src.programme_tools.narrative.compose_narrative",
               side_effect=lambda res, ctx=None, use_llm=True: res.summary):
        wr = _run("show milestone movements as a chart", _stub_router())
    first = wr.blocks[0]
    assert first["type"] == "markdown_text"
    assert first["block_id"] == "input_resolution"
