"""Query-pattern memory — secondary planner signal, registry-validated.

Each test uses a unique query so the (persistent) telemetry DB can't leak
counts between runs; query_patterns reads global history by signature.
"""

import uuid

from src.learning import query_patterns as qp
from src.learning.workflow_telemetry import record_workflow_run
from src.workflows.types import WorkflowContext, WorkflowId, WorkflowResult


class _Plan:
    source = "deterministic"


def _uniq(base):
    return f"{base} {uuid.uuid4().hex}"


def _seed(query, wid, status, n):
    for _ in range(n):
        wr = WorkflowResult(workflow_id=wid, status=status, blocks=[])
        record_workflow_run(wr, WorkflowContext(user_query=query,
                                                corpus_id="qptest"), _Plan())


def test_dominant_successful_pattern_is_suggested():
    q = _uniq("dcma health check")
    _seed(q, WorkflowId.DCMA_LATEST, "success", 4)
    s = qp.suggest(q)
    assert s is not None
    assert s["workflow_id"] == WorkflowId.DCMA_LATEST
    assert s["sample_count"] == 4
    assert 0.75 <= s["confidence"] <= 1.0


def test_novel_query_returns_none():
    assert qp.suggest(_uniq("never seen before")) is None


def test_below_min_samples_returns_none():
    q = _uniq("sparse pattern")
    _seed(q, WorkflowId.PROGRAMME_INVENTORY, "success", 1)
    assert qp.suggest(q) is None


def test_failed_runs_do_not_create_a_signal():
    q = _uniq("always failing")
    _seed(q, WorkflowId.SQL_METRIC_CHART, "failed", 5)
    assert qp.suggest(q) is None


def test_suggestion_only_points_at_available_workflows():
    # Even a DOMINANT successful history for a planned/unavailable id must be
    # refused — the memory can only route to a runnable workflow.
    q = _uniq("planned method viability history")
    _seed(q, WorkflowId.METHOD_VIABILITY, "success", 5)
    assert qp.suggest(q) is None


def test_high_risk_prompts_never_routed_by_memory():
    # Even with a dominant successful history, causation/entitlement/liability/
    # drafting intents must never get a memory route.
    for base in ("who caused the delay", "is the contractor entitled to an eot",
                 "assess liability for the delay", "draft a reply letter"):
        q = _uniq(base)
        _seed(q, WorkflowId.DCMA_LATEST, "success", 5)
        assert qp.suggest(q) is None, base


def test_unknown_workflow_id_in_history_is_safe(monkeypatch):
    # A renamed/removed id dominating the history must degrade to None, not crash.
    import src.learning.workflow_telemetry as wt
    monkeypatch.setattr(wt, "runs_for_query_signature", lambda sig, limit=50: [
        {"workflow_id": "removed_legacy_id", "status": "success", "count": 9}])
    assert qp.suggest("some legacy query") is None
