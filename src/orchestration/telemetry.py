"""Orchestration step telemetry — one row per executed step, best-effort.

Rides the interaction_log DuckDB singleton (same lifecycle as
trust_guard_runs); never blocks or raises into the chat path.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS orchestration_steps ("
    "run_id VARCHAR, step_id VARCHAR, tool_id VARCHAR, attempt INTEGER, "
    "status VARCHAR, latency_ms DOUBLE, fallback_used VARCHAR, "
    "reason VARCHAR, ts VARCHAR)"
)

_table_ready = False


def log_step(run_id: str, step_id: str, tool_id: str, attempt: int,
             status: str, latency_ms: float, fallback_used: str = "",
             reason: str = "", ts: Optional[str] = None) -> None:
    global _table_ready
    try:
        from datetime import datetime
        from src.interaction_log import get_interaction_log
        log = get_interaction_log()
        with log._db_lock:
            if not _table_ready:
                log._con.execute(_TABLE_SQL)
                _table_ready = True
            log._con.execute(
                "INSERT INTO orchestration_steps VALUES (?,?,?,?,?,?,?,?,?)",
                [run_id, step_id, tool_id, int(attempt), status,
                 float(latency_ms), fallback_used, (reason or "")[:400],
                 ts or datetime.now().isoformat()],
            )
    except Exception as e:
        logger.debug(f"[Orchestration] telemetry skipped: {e}")
