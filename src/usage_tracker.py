"""
Application-wide token/cost budget tracker.

A single shared budget that all conversations deduct from. Backed by Redis
when REDIS_URL is set; falls back to a JSON file under STORAGE_DIR.

The limit is configured via env var COAIR_USAGE_LIMIT_USD (default: 100.0).
For backward compatibility with earlier deploys, ASISTANT_USAGE_LIMIT_USD is
still honoured if the new var is unset.
When the cumulative cost crosses the limit, `is_over_budget()` returns True
and `enforce_budget()` raises BudgetExceededError, which the LLM client should
surface to the API layer (returned as HTTP 402).
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from .config import REDIS_URL, STORAGE_DIR
from .logger import logger


# ── Settings ──────────────────────────────────────────────────

USAGE_LIMIT_USD: float = float(
    os.getenv("COAIR_USAGE_LIMIT_USD") or os.getenv("ASISTANT_USAGE_LIMIT_USD") or "100.0"
)

_REDIS_KEY_PREFIX = "coair:usage:"
_REDIS_KEY_USED_USD = _REDIS_KEY_PREFIX + "used_usd"
_REDIS_KEY_PROMPT_TOKENS = _REDIS_KEY_PREFIX + "prompt_tokens"
_REDIS_KEY_COMPLETION_TOKENS = _REDIS_KEY_PREFIX + "completion_tokens"
_REDIS_KEY_TOTAL_CALLS = _REDIS_KEY_PREFIX + "total_calls"

_FILE_PATH = Path(STORAGE_DIR) / "usage_counter.json"
_FILE_LOCK = threading.Lock()


class BudgetExceededError(RuntimeError):
    """Raised when the global usage budget has been reached."""


@dataclass
class UsageSnapshot:
    used_usd: float
    limit_usd: float
    remaining_usd: float
    remaining_pct: float
    over_budget: bool
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    total_calls: int


# ── Backend selection ─────────────────────────────────────────

_redis = None
_redis_attempted = False


def _get_redis():
    """Return a redis client if REDIS_URL is configured, else None."""
    global _redis, _redis_attempted
    if _redis_attempted:
        return _redis
    _redis_attempted = True
    if not REDIS_URL:
        return None
    try:
        import redis  # type: ignore
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
        # Probe to make sure it works
        _redis.ping()
        logger.info("[UsageTracker] Using Redis backend")
    except Exception as e:
        logger.warning(f"[UsageTracker] Redis unavailable ({e}); using file backend")
        _redis = None
    return _redis


# ── File backend ──────────────────────────────────────────────

def _read_file_state() -> dict:
    if not _FILE_PATH.exists():
        return {"used_usd": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "total_calls": 0}
    try:
        with _FILE_PATH.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {"used_usd": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "total_calls": 0}


def _write_file_state(state: dict) -> None:
    _FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _FILE_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(state, fh)
    tmp.replace(_FILE_PATH)


# ── Public API ────────────────────────────────────────────────

def record_usage(prompt_tokens: int, completion_tokens: int, cost_usd: float) -> None:
    """Atomically add the deltas to the global counter."""
    if cost_usd < 0 or (prompt_tokens == 0 and completion_tokens == 0 and cost_usd == 0):
        return

    r = _get_redis()
    if r is not None:
        try:
            pipe = r.pipeline()
            pipe.incrbyfloat(_REDIS_KEY_USED_USD, float(cost_usd))
            pipe.incrby(_REDIS_KEY_PROMPT_TOKENS, int(prompt_tokens))
            pipe.incrby(_REDIS_KEY_COMPLETION_TOKENS, int(completion_tokens))
            pipe.incrby(_REDIS_KEY_TOTAL_CALLS, 1)
            pipe.execute()
            return
        except Exception as e:
            logger.warning(f"[UsageTracker] Redis incr failed ({e}); falling back to file")

    with _FILE_LOCK:
        state = _read_file_state()
        state["used_usd"] = float(state.get("used_usd", 0.0)) + float(cost_usd)
        state["prompt_tokens"] = int(state.get("prompt_tokens", 0)) + int(prompt_tokens)
        state["completion_tokens"] = int(state.get("completion_tokens", 0)) + int(completion_tokens)
        state["total_calls"] = int(state.get("total_calls", 0)) + 1
        _write_file_state(state)


def get_snapshot() -> UsageSnapshot:
    """Return the current cumulative usage snapshot."""
    used = 0.0
    pt = 0
    ct = 0
    calls = 0

    r = _get_redis()
    if r is not None:
        try:
            used = float(r.get(_REDIS_KEY_USED_USD) or 0.0)
            pt = int(r.get(_REDIS_KEY_PROMPT_TOKENS) or 0)
            ct = int(r.get(_REDIS_KEY_COMPLETION_TOKENS) or 0)
            calls = int(r.get(_REDIS_KEY_TOTAL_CALLS) or 0)
        except Exception as e:
            logger.warning(f"[UsageTracker] Redis read failed ({e}); falling back to file")
            r = None

    if r is None:
        with _FILE_LOCK:
            state = _read_file_state()
        used = float(state.get("used_usd", 0.0))
        pt = int(state.get("prompt_tokens", 0))
        ct = int(state.get("completion_tokens", 0))
        calls = int(state.get("total_calls", 0))

    limit = USAGE_LIMIT_USD
    remaining_usd = max(0.0, limit - used)
    remaining_pct = max(0.0, min(1.0, remaining_usd / limit)) if limit > 0 else 0.0
    return UsageSnapshot(
        used_usd=round(used, 6),
        limit_usd=round(limit, 2),
        remaining_usd=round(remaining_usd, 6),
        remaining_pct=round(remaining_pct, 4),
        over_budget=used >= limit > 0,
        prompt_tokens=pt,
        completion_tokens=ct,
        total_tokens=pt + ct,
        total_calls=calls,
    )


def is_over_budget() -> bool:
    return get_snapshot().over_budget


def enforce_budget() -> None:
    """Raise BudgetExceededError if the budget has been spent."""
    snap = get_snapshot()
    if snap.over_budget:
        raise BudgetExceededError(
            f"Application usage limit reached: ${snap.used_usd:.4f} / ${snap.limit_usd:.2f}"
        )


def reset_usage() -> UsageSnapshot:
    """Reset the global counter. Intended for admin use only."""
    r = _get_redis()
    if r is not None:
        try:
            r.delete(
                _REDIS_KEY_USED_USD,
                _REDIS_KEY_PROMPT_TOKENS,
                _REDIS_KEY_COMPLETION_TOKENS,
                _REDIS_KEY_TOTAL_CALLS,
            )
        except Exception as e:
            logger.warning(f"[UsageTracker] Redis reset failed ({e})")

    with _FILE_LOCK:
        _write_file_state({"used_usd": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "total_calls": 0})
    return get_snapshot()


def snapshot_dict() -> dict:
    return asdict(get_snapshot())


__all__ = [
    "BudgetExceededError",
    "UsageSnapshot",
    "USAGE_LIMIT_USD",
    "record_usage",
    "get_snapshot",
    "is_over_budget",
    "enforce_budget",
    "reset_usage",
    "snapshot_dict",
]
