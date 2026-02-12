"""
Per-query telemetry: tracks LLM calls, latency, cost, cache hits.
"""
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import TELEMETRY_LOG_DIR
from .types import LLMUsage
from .logger import logger


@dataclass
class QueryTrace:
    """Telemetry trace for a single user query."""
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    query: str = ""
    route: str = ""                   # DOCUMENT / DATA / TIMELINE / HYBRID
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_estimate: float = 0.0
    latency_ms: float = 0.0
    cache_hits: int = 0
    errors: List[str] = field(default_factory=list)
    steps: List[Dict[str, Any]] = field(default_factory=list)
    provider_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    _start_time: float = field(default_factory=time.time, repr=False)

    def _ensure_provider(self, provider: str):
        """Ensure provider stats entry exists."""
        if provider and provider not in self.provider_stats:
            self.provider_stats[provider] = {
                "calls": 0, "tokens_in": 0, "tokens_out": 0,
                "cost": 0.0, "cache_hits": 0,
            }

    def record_llm_call(self, usage: LLMUsage):
        """Record a single LLM call's usage into the trace."""
        self.llm_calls += 1
        self.tokens_in += usage.prompt_tokens
        self.tokens_out += usage.completion_tokens
        self.cost_estimate += usage.cost_estimate
        if usage.cache_hit:
            self.cache_hits += 1

        # Per-provider tracking
        if usage.provider:
            self._ensure_provider(usage.provider)
            ps = self.provider_stats[usage.provider]
            ps["calls"] += 1
            ps["tokens_in"] += usage.prompt_tokens
            ps["tokens_out"] += usage.completion_tokens
            ps["cost"] += usage.cost_estimate
            if usage.cache_hit:
                ps["cache_hits"] += 1

    def record_error(self, error: str):
        self.errors.append(error)

    def record_step(self, step_id: int, step_type: str, status: str, latency_ms: float = 0):
        self.steps.append({
            "step_id": step_id, "type": step_type,
            "status": status, "latency_ms": latency_ms,
        })

    def finish(self):
        """Finalize the trace with total latency."""
        self.latency_ms = round((time.time() - self._start_time) * 1000, 1)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop('_start_time', None)
        return d

    def save(self):
        """Persist trace to JSONL log file."""
        self.finish()
        log_path = Path(TELEMETRY_LOG_DIR) / "traces.jsonl"
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(self.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"[Telemetry] Could not write trace: {e}")

    def summary(self) -> str:
        """Human-readable one-line summary."""
        parts = [
            f"[Trace {self.request_id}] route={self.route}",
            f"llm_calls={self.llm_calls} cache_hits={self.cache_hits}",
            f"tokens={self.tokens_in}+{self.tokens_out}",
            f"cost=${self.cost_estimate:.6f} latency={self.latency_ms:.0f}ms",
        ]
        if self.errors:
            parts.append(f"errors={len(self.errors)}")
        if self.provider_stats:
            prov_parts = []
            for prov, ps in self.provider_stats.items():
                prov_parts.append(f"{prov}({ps['calls']}calls/${ps['cost']:.4f})")
            parts.append(f"providers=[{', '.join(prov_parts)}]")
        return " ".join(parts)


# ── Thread-local current trace ───────────────────────────────

import threading
_local = threading.local()


def start_trace(query: str = "") -> QueryTrace:
    """Start a new trace for the current request."""
    trace = QueryTrace(query=query)
    _local.current_trace = trace
    return trace


def get_current_trace() -> Optional[QueryTrace]:
    """Get the current request's trace (if any)."""
    return getattr(_local, 'current_trace', None)


def finish_trace() -> Optional[QueryTrace]:
    """Finish and save the current trace."""
    trace = getattr(_local, 'current_trace', None)
    if trace:
        trace.save()
        logger.info(trace.summary())
        _local.current_trace = None
    return trace
