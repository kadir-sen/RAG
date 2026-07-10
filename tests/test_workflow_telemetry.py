"""Workflow telemetry — best-effort write, never breaks the run."""

from src.learning.workflow_telemetry import (
    query_signature, record_workflow_run, recent_runs,
)
from src.workflows.types import WorkflowContext, WorkflowId, WorkflowResult


def test_query_signature_normalizes():
    a = query_signature("Show milestone movements as a chart")
    b = query_signature("please show the milestone movements chart")
    assert "milestone" in a and "movements" in a
    assert a == b   # same core terms, different filler → same signature


def test_record_writes_a_row():
    wr = WorkflowResult(workflow_id=WorkflowId.PROGRAMME_INVENTORY,
                        status="success",
                        blocks=[{"type": "data_table"}],
                        caveats=["only one revision"])
    ctx = WorkflowContext(user_query="what programme files are available",
                          corpus_id="test_corpus")

    class _Plan:
        source = "deterministic"

    before = len(recent_runs(corpus="test_corpus"))
    record_workflow_run(wr, ctx, _Plan(), latency_ms=12.3)
    after = recent_runs(corpus="test_corpus")
    assert len(after) >= before + 1
    assert after[0]["workflow_id"] == "programme_inventory"
    assert after[0]["status"] == "success"


def test_record_never_raises_on_garbage():
    # Missing attributes must degrade silently, never propagate.
    record_workflow_run(object(), object(), object())
