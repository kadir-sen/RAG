"""Step execution with declarative retry + fallback + telemetry."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

from .schemas import RetryPolicy, StepResult
from .telemetry import log_step

logger = logging.getLogger(__name__)


def execute_step(run_id: str, step_id: str, capability_id: str,
                 fn: Callable[[int], Any],
                 retry: Optional[RetryPolicy] = None,
                 fallback_fn: Optional[Callable[[Exception | str], Any]] = None,
                 ) -> StepResult:
    """Run one plan step: attempt → retry per policy → fallback.

    fn(attempt) returns the step output or raises / returns a (None, reason)
    tuple to signal failure. fallback_fn produces the fallback output.
    Telemetry per attempt; never raises to the caller.
    """
    retry = retry or RetryPolicy()
    t0 = time.perf_counter()
    last_reason = ""
    for attempt in range(1, retry.max_retries + 2):
        try:
            out = fn(attempt)
            if isinstance(out, tuple) and len(out) == 2 and out[0] is None:
                last_reason = str(out[1])
                log_step(run_id, step_id, capability_id, attempt, "failed",
                         (time.perf_counter() - t0) * 1000, reason=last_reason)
                continue
            latency = (time.perf_counter() - t0) * 1000
            log_step(run_id, step_id, capability_id, attempt, "ok", latency)
            return StepResult(step_id=step_id, capability_id=capability_id,
                              status="ok", output=out, guard_status="passed",
                              attempts=attempt, latency_ms=latency)
        except Exception as e:
            last_reason = str(e)
            logger.warning(f"[Orchestration] {step_id} attempt {attempt} failed: {e}")
            log_step(run_id, step_id, capability_id, attempt, "failed",
                     (time.perf_counter() - t0) * 1000, reason=last_reason)

    latency = (time.perf_counter() - t0) * 1000
    if fallback_fn is not None:
        try:
            fb = fallback_fn(last_reason)
            log_step(run_id, step_id, capability_id, retry.max_retries + 1,
                     "fallback", latency, fallback_used=retry.fallback,
                     reason=last_reason)
            return StepResult(step_id=step_id, capability_id=capability_id,
                              status="fallback", output=fb,
                              guard_status="fallback",
                              fallback_used=retry.fallback,
                              attempts=retry.max_retries + 1,
                              latency_ms=latency, reason=last_reason)
        except Exception as e:
            logger.warning(f"[Orchestration] {step_id} fallback failed: {e}")

    return StepResult(step_id=step_id, capability_id=capability_id,
                      status="failed", guard_status="failed",
                      attempts=retry.max_retries + 1, latency_ms=latency,
                      reason=last_reason)
