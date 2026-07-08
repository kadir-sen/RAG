"""Per-call LLM usage ledger — one row per gateway invocation, best-effort.

Rides the interaction_log DuckDB singleton (same lifecycle as
trust_guard_runs). customer_id/project_id are the plug-in seam for the
out-of-scope per-$ budgets + cost dashboard: present now, populated later.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS llm_usage_events ("
    "event_id VARCHAR PRIMARY KEY, ts VARCHAR, run_id VARCHAR, "
    "username VARCHAR, task_type VARCHAR, provider VARCHAR, "
    "model_id VARCHAR, model_group VARCHAR, fallback_level INTEGER, "
    "input_tokens INTEGER, output_tokens INTEGER, est_cost_usd DOUBLE, "
    "latency_ms DOUBLE, status VARCHAR, error_type VARCHAR, "
    "customer_id VARCHAR, project_id VARCHAR)"
)

_ready = False
_seq = 0


def log_usage_event(*, run_id: str = "", username: str = "", task_type: str = "",
                    provider: str = "", model_id: str = "", model_group: str = "",
                    fallback_level: int = 0, input_tokens: int = 0,
                    output_tokens: int = 0, est_cost_usd: float = 0.0,
                    latency_ms: float = 0.0, status: str = "success",
                    error_type: Optional[str] = None,
                    customer_id: str = "", project_id: str = "") -> None:
    global _ready, _seq
    try:
        from datetime import datetime
        from src.interaction_log import get_interaction_log
        log = get_interaction_log()
        _seq += 1
        ts = datetime.now().isoformat()
        eid = hashlib.sha256(
            f"{ts}|{run_id}|{task_type}|{model_id}|{_seq}".encode()
        ).hexdigest()[:24]
        with log._db_lock:
            if not _ready:
                log._con.execute(_TABLE_SQL)
                _ready = True
            log._con.execute(
                "INSERT OR IGNORE INTO llm_usage_events VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [eid, ts, run_id, username, task_type, provider, model_id,
                 model_group, int(fallback_level), int(input_tokens),
                 int(output_tokens), float(est_cost_usd), float(latency_ms),
                 status, error_type or "", customer_id, project_id],
            )
    except Exception as e:
        logger.debug(f"[LLMUsage] event log skipped: {e}")


def usage_stats(days: int = 7) -> dict:
    """Aggregate for a future admin panel (schema present now)."""
    try:
        from datetime import datetime, timedelta
        from src.interaction_log import get_interaction_log
        log = get_interaction_log()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with log._db_lock:
            log._con.execute(_TABLE_SQL)
            total, cost = log._con.execute(
                "SELECT COUNT(*), COALESCE(SUM(est_cost_usd),0) "
                "FROM llm_usage_events WHERE ts >= ?", [cutoff]).fetchone()
            by_status = dict(log._con.execute(
                "SELECT status, COUNT(*) FROM llm_usage_events "
                "WHERE ts >= ? GROUP BY status", [cutoff]).fetchall())
            by_task = dict(log._con.execute(
                "SELECT task_type, COUNT(*) FROM llm_usage_events "
                "WHERE ts >= ? GROUP BY task_type", [cutoff]).fetchall())
            fallback_rate = log._con.execute(
                "SELECT COALESCE(AVG(CASE WHEN fallback_level>0 THEN 1.0 ELSE 0 END),0) "
                "FROM llm_usage_events WHERE ts >= ?", [cutoff]).fetchone()[0]
        return {"total_calls": int(total), "est_cost_usd": round(float(cost), 4),
                "by_status": {str(k): int(v) for k, v in by_status.items()},
                "by_task": {str(k): int(v) for k, v in by_task.items()},
                "fallback_rate": round(float(fallback_rate), 3)}
    except Exception as e:
        logger.debug(f"[LLMUsage] stats failed: {e}")
        return {"total_calls": 0, "est_cost_usd": 0.0, "by_status": {},
                "by_task": {}, "fallback_rate": 0.0}
