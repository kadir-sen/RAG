"""
Unified LLM client with caching, cost tracking, retries, and timeouts.
All LLM calls in the system should go through this module.
"""
import hashlib
import json
import time
from typing import Any, Dict, List, Optional

from .config import (
    GOOGLE_API_KEY, GEMINI_MODEL,
    LLM_PRICING, CACHE_DIR, CACHE_TTL_SECONDS, REDIS_URL,
    LLM_TIMEOUT_SECONDS, LLM_MAX_RETRIES,
)
from .types import LLMUsage, LLMResponse
from .logger import logger

# ── Cache Backend ────────────────────────────────────────────

_cache = None


def _get_cache():
    """Get or create cache backend (diskcache or Redis)."""
    global _cache
    if _cache is not None:
        return _cache

    if REDIS_URL:
        try:
            import redis
            _cache = redis.from_url(REDIS_URL)
            logger.info("[LLMClient] Using Redis cache")
            return _cache
        except Exception as e:
            logger.warning(f"[LLMClient] Redis unavailable ({e}), falling back to disk")

    try:
        import diskcache
        _cache = diskcache.Cache(CACHE_DIR, size_limit=500 * 1024 * 1024)  # 500 MB
        logger.info(f"[LLMClient] Using disk cache at {CACHE_DIR}")
    except ImportError:
        logger.warning("[LLMClient] diskcache not installed, caching disabled")
        _cache = {}

    return _cache


def _cache_get(key: str) -> Optional[str]:
    cache = _get_cache()
    if cache is None:
        return None
    try:
        if hasattr(cache, 'get'):
            val = cache.get(key)
            if isinstance(val, bytes):
                return val.decode('utf-8')
            return val
        return None
    except Exception:
        return None


def _cache_set(key: str, value: str, ttl: int):
    cache = _get_cache()
    if cache is None:
        return
    try:
        if hasattr(cache, 'set'):
            cache.set(key, value, expire=ttl)
    except Exception:
        pass


# ── Cost Estimation ──────────────────────────────────────────

def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate cost in USD for a given call."""
    pricing = LLM_PRICING.get(model, LLM_PRICING.get("gemini-flash-latest", {}))
    input_cost = (prompt_tokens / 1_000_000) * pricing.get("input", 0.075)
    output_cost = (completion_tokens / 1_000_000) * pricing.get("output", 0.30)
    return round(input_cost + output_cost, 8)


def estimate_tokens(text: str) -> int:
    """Rough token estimate (chars / 4)."""
    return max(1, len(text) // 4)


# ── Core API ─────────────────────────────────────────────────

def generate_text(
    prompt: str,
    *,
    system: str = "",
    model: str = "",
    temperature: float = 0.1,
    max_tokens: int = 2048,
    json_mode: bool = False,
    cache_key: Optional[str] = None,
    ttl_s: int = CACHE_TTL_SECONDS,
) -> LLMResponse:
    """
    Generate text via Gemini, with caching and usage tracking.

    Args:
        prompt: The user/task prompt
        system: System instruction (prepended)
        model: Model name override
        temperature: Sampling temperature
        max_tokens: Max output tokens
        json_mode: If True, hint the model to return JSON
        cache_key: Explicit cache key; if None, auto-derived from prompt
        ttl_s: Cache TTL in seconds

    Returns:
        LLMResponse with text, usage info, cache status
    """
    model = model or GEMINI_MODEL

    # ── Build cache key ──
    if cache_key is None:
        key_data = f"{model}:{system[:200]}:{prompt}"
        cache_key = "llm:" + hashlib.sha256(key_data.encode()).hexdigest()[:32]

    # ── Check cache ──
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info(f"[LLMClient] Cache HIT ({cache_key[:16]}...)")
        prompt_tok = estimate_tokens(prompt + system)
        comp_tok = estimate_tokens(cached)
        return LLMResponse(
            text=cached,
            usage=LLMUsage(
                prompt_tokens=prompt_tok,
                completion_tokens=comp_tok,
                total_tokens=prompt_tok + comp_tok,
                cost_estimate=0.0,  # cached = free
                model=model,
                latency_ms=0.0,
                cache_hit=True,
            ),
        )

    # ── Call LLM ──
    from llama_index.llms.gemini import Gemini

    llm = Gemini(
        api_key=GOOGLE_API_KEY,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    full_prompt = prompt
    if system:
        full_prompt = f"{system}\n\n{prompt}"

    last_error = None
    for attempt in range(1 + LLM_MAX_RETRIES):
        try:
            start = time.time()
            response = llm.complete(full_prompt)
            elapsed_ms = (time.time() - start) * 1000
            text = response.text.strip()

            # ── Build usage ──
            prompt_tok = estimate_tokens(full_prompt)
            comp_tok = estimate_tokens(text)
            cost = estimate_cost(model, prompt_tok, comp_tok)

            usage = LLMUsage(
                prompt_tokens=prompt_tok,
                completion_tokens=comp_tok,
                total_tokens=prompt_tok + comp_tok,
                cost_estimate=cost,
                model=model,
                latency_ms=round(elapsed_ms, 1),
                cache_hit=False,
            )

            logger.info(
                f"[LLMClient] {model} | {prompt_tok}+{comp_tok} tok | "
                f"${cost:.6f} | {elapsed_ms:.0f}ms"
            )

            # ── Cache result ──
            _cache_set(cache_key, text, ttl_s)

            return LLMResponse(text=text, usage=usage, raw=response)

        except Exception as e:
            last_error = e
            if attempt < LLM_MAX_RETRIES:
                wait = 2 ** attempt
                logger.warning(f"[LLMClient] Retry {attempt+1} after {wait}s: {e}")
                time.sleep(wait)
            else:
                logger.error(f"[LLMClient] Failed after {1 + LLM_MAX_RETRIES} attempts: {e}")

    raise RuntimeError(f"LLM call failed: {last_error}")


def generate_json(
    prompt: str,
    *,
    system: str = "",
    model: str = "",
    cache_key: Optional[str] = None,
    ttl_s: int = CACHE_TTL_SECONDS,
) -> LLMResponse:
    """Generate text and parse as JSON. Raises on invalid JSON."""
    import re as _re

    resp = generate_text(
        prompt, system=system, model=model,
        json_mode=True, cache_key=cache_key, ttl_s=ttl_s,
    )

    # Strip markdown fences
    raw = resp.text
    if raw.startswith("```"):
        raw = _re.sub(r'^```(?:json)?\s*', '', raw)
        raw = _re.sub(r'\s*```$', '', raw)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract JSON object
        match = _re.search(r'\{[\s\S]+\}', raw)
        if match:
            parsed = json.loads(match.group())
        else:
            raise ValueError(f"LLM did not return valid JSON: {raw[:200]}")

    resp.text = json.dumps(parsed)
    resp.raw = parsed
    return resp
