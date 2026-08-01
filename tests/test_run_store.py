import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.run_store import RunStore
from src.types import LLMUsage


def test_run_store_reports_steps_tokens_cost_and_project_scope(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    run_id = store.start(
        project_id="p1", username="alice", module="chronology", query="access",
        prompt_version="v1",
    )
    store.add_step(run_id, "retrieval", "Dense retrieval")
    store.add_step(run_id, "verification", "Claim rejected", status="fallback")
    store.record_llm(LLMUsage(
        provider="openai", model="gpt-5.6-sol", prompt_tokens=100,
        completion_tokens=20, reasoning_tokens=7, cached_tokens=40,
        cost_estimate=0.0012, latency_ms=250,
    ), run_id)
    store.finish(run_id, source_count=4, footnote_count=6, verification="PASS")

    assert store.recent(project_id="p2", admin=True) == []
    row = store.recent(project_id="p1", admin=True)[0]
    assert row["total_steps"] == 2
    assert row["successful_steps"] == 1
    assert row["fallback_steps"] == 1
    assert row["input_tokens"] == 100
    assert row["reasoning_tokens"] == 7
    assert row["cached_tokens"] == 40
    assert row["cost_usd"] == 0.0012
    assert row["footnote_count"] == 6


def test_legacy_run_metrics_remain_unknown_not_zero(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    with store._connect() as conn:
        conn.execute(
            "INSERT INTO query_runs "
            "(run_id,username,module,query,status,created_at,metrics_complete) "
            "VALUES ('legacy','admin','chat','old','completed','2025-01-01',0)"
        )
    row = store.recent(admin=True)[0]
    assert row["total_steps"] is None
    assert row["cost_usd"] is None
    assert row["latency_ms"] is None
