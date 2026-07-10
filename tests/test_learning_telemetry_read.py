"""Workflow telemetry read-side + admin endpoints."""

from src.learning import telemetry_summary, recent_runs, record_workflow_run
from src.learning.workflow_telemetry import runs_for_query_signature
from src.workflows.types import WorkflowContext, WorkflowId, WorkflowResult


class _Plan:
    source = "deterministic"


def _record(wid, status, corpus, query):
    wr = WorkflowResult(workflow_id=wid, status=status,
                        blocks=[{"type": "markdown_text"}])
    ctx = WorkflowContext(user_query=query, corpus_id=corpus)
    record_workflow_run(wr, ctx, _Plan(), latency_ms=5.0)


def test_summary_shape_and_aggregation():
    _record(WorkflowId.DCMA_LATEST, "success", "tsum", "run dcma latest")
    _record(WorkflowId.DCMA_LATEST, "partial", "tsum", "run dcma on latest")
    s = telemetry_summary(corpus="tsum")
    assert s["total_runs"] >= 2
    assert s["by_workflow"].get("dcma_latest", 0) >= 2
    assert set(s.keys()) >= {"total_runs", "by_workflow", "by_status",
                             "analyst_review_runs", "avg_latency_ms"}


def test_recent_runs_and_signature_lookup():
    _record(WorkflowId.PROGRAMME_INVENTORY, "success", "tsig",
            "what programme files are available")
    runs = recent_runs(corpus="tsig", limit=5)
    assert runs and runs[0]["workflow_id"] == "programme_inventory"
    from src.learning.workflow_telemetry import query_signature
    sig = query_signature("what programme files are available")
    grouped = runs_for_query_signature(sig)
    assert any(g["workflow_id"] == "programme_inventory" for g in grouped)


def test_admin_endpoints_callable():
    from backend.api.admin import (schema_pending, schema_confirm,
                                   workflow_telemetry, SchemaConfirmRequest)
    p = schema_pending()
    assert p["ok"] and "pending" in p
    bad = schema_confirm(SchemaConfirmRequest())
    assert bad["ok"] is False                       # nothing provided
    t = workflow_telemetry(corpus="tsum")
    assert t["ok"] and "recent" in t and "by_workflow" in t
