"""LLM Gateway — the single entrypoint every LLM-dependent task goes through.

Wraps (does not replace) src.llm_client: it resolves a task→model chain,
invokes the existing generate_text/generate_json per model, enforces a
timeout (LLM_TIMEOUT_SECONDS, previously never applied), walks the fallback
chain on classified errors, sanitizes provider errors, logs usage, and never
lets a raw 429/quota/billing string reach the caller.
"""

from __future__ import annotations

import concurrent.futures
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from . import errors, policy, usage
from .registry import ModelSpec

logger = logging.getLogger(__name__)


@dataclass
class GatewayResult:
    text: str = ""
    raw: Any = None                 # parsed JSON when json_mode
    usage: Any = None               # LLMUsage
    model_used: Optional[str] = None   # logical model_id, or None
    fallback_level: int = 0            # 0=primary, 1..n=fell back, -1=deterministic
    status: str = "success"            # success | fallback | degraded
    degraded_message: str = ""
    error_type: Optional[str] = None


def _run_id() -> str:
    try:
        from backend.tasks.query_progress import query_request_var
        rid = query_request_var.get()
        if rid:
            return rid
    except Exception:
        pass
    return uuid.uuid4().hex[:12]


def _username() -> str:
    try:
        from backend.core.security import get_current_username
        return get_current_username() or ""
    except Exception:
        return ""


def _record_trace(resp_usage) -> None:
    try:
        from src.telemetry import get_current_trace
        tr = get_current_trace()
        if tr is not None and resp_usage is not None:
            tr.record_llm_call(resp_usage)
    except Exception:
        pass


def _invoke(spec: ModelSpec, prompt: str, system: str, json_mode: bool,
            max_tokens: int, timeout_s: int):
    """Call the existing llm_client under a hard timeout. Raises on failure
    (including a synthetic timeout) so the gateway's fallback rules apply."""
    from src import llm_client

    def _call():
        if json_mode:
            return llm_client.generate_json(
                prompt, system=system, model=spec.provider_model_name,
                provider=spec.provider)
        return llm_client.generate_text(
            prompt, system=system, model=spec.provider_model_name,
            provider=spec.provider, max_tokens=max_tokens)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_call)
        try:
            return fut.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError as e:
            raise RuntimeError(f"LLM call timeout after {timeout_s}s") from e


def complete(task_type: str, prompt: str, *, system: str = "",
             deterministic_fn: Optional[Callable[[], GatewayResult]] = None,
             cache_key: Optional[str] = None) -> GatewayResult:
    """Run one task through its fallback chain. Never raises to the caller
    except BudgetExceededError/UserQuotaExceededError (which must reach 402)."""
    chain = policy.select(task_type)
    pol = chain.policy
    run_id, user = _run_id(), _username()
    last_error_type = errors.LLMErrorType.PROVIDER_DOWN

    for level, spec in enumerate(chain.models):
        attempt = 0
        while True:
            attempt += 1
            t0 = time.perf_counter()
            try:
                resp = _invoke(spec, prompt, system, pol.json_mode,
                               pol.max_output_tokens, pol.timeout_s)
                latency = (time.perf_counter() - t0) * 1000
                _record_trace(getattr(resp, "usage", None))
                u = getattr(resp, "usage", None)
                usage.log_usage_event(
                    run_id=run_id, username=user, task_type=task_type,
                    provider=spec.provider, model_id=spec.model_id,
                    model_group=pol.model_group, fallback_level=level,
                    input_tokens=getattr(u, "prompt_tokens", 0),
                    output_tokens=getattr(u, "completion_tokens", 0),
                    est_cost_usd=getattr(u, "cost_estimate", 0.0),
                    latency_ms=latency,
                    status="success" if level == 0 else "fallback")
                return GatewayResult(
                    text=getattr(resp, "text", ""), raw=getattr(resp, "raw", None),
                    usage=u, model_used=spec.model_id, fallback_level=level,
                    status="success" if level == 0 else "fallback")
            except Exception as e:
                # Budget/quota re-raise inside classify_error → propagate to 402.
                etype = errors.classify_error(e)
                last_error_type = etype
                latency = (time.perf_counter() - t0) * 1000
                usage.log_usage_event(
                    run_id=run_id, username=user, task_type=task_type,
                    provider=spec.provider, model_id=spec.model_id,
                    model_group=pol.model_group, fallback_level=level,
                    latency_ms=latency, status="error", error_type=etype.value)
                if (attempt == 1 and errors.allows_same_model_retry(etype)
                        and attempt <= pol.retries):
                    continue  # one same-model retry (timeout / malformed json)
                break  # advance to next model in the chain

    # Chain exhausted → deterministic path, then fail-open / degraded.
    if pol.deterministic_fallback and deterministic_fn is not None:
        try:
            det = deterministic_fn()
            det.fallback_level = -1
            det.status = det.status or "success"
            return det
        except Exception as e:
            logger.warning(f"[Gateway] deterministic fallback failed: {e}")

    msg = errors.sanitize(pol, last_error_type)
    if pol.fail_open:
        return GatewayResult(text="", status="degraded", degraded_message=msg,
                             error_type=last_error_type.value)
    return GatewayResult(text=msg, status="degraded", degraded_message=msg,
                         error_type=last_error_type.value)
