"""
Unified LLM client with caching, cost tracking, retries, and timeouts.
Supports multiple providers: Gemini, OpenAI, Claude (Anthropic).
All LLM calls in the system should go through this module.
"""
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from .config import (
    GOOGLE_API_KEY, GEMINI_MODEL,
    OPENAI_API_KEY, OPENAI_MODEL,
    ANTHROPIC_API_KEY, ANTHROPIC_MODEL,
    LLM_PRICING, CACHE_DIR, CACHE_TTL_SECONDS, REDIS_URL,
    LLM_TIMEOUT_SECONDS, LLM_MAX_RETRIES, LLM_PROVIDERS,
)
from .types import LLMUsage, LLMResponse, DualLLMResponse
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


# ── LLM Factory ─────────────────────────────────────────────

def create_llm(provider: str, temperature: float = 0.1, max_tokens: int = 2048):
    """
    Create a LlamaIndex LLM instance for the given provider.

    Args:
        provider: "openai" | "claude" | "gemini"
        temperature: Sampling temperature
        max_tokens: Max output tokens

    Returns:
        Tuple of (llm_instance, model_name)
    """
    if provider == "openai":
        from llama_index.llms.openai import OpenAI
        model = OPENAI_MODEL
        llm = OpenAI(
            api_key=OPENAI_API_KEY,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return llm, model
    elif provider == "claude":
        from llama_index.llms.anthropic import Anthropic
        model = ANTHROPIC_MODEL
        llm = Anthropic(
            api_key=ANTHROPIC_API_KEY,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return llm, model
    else:
        from llama_index.llms.gemini import Gemini
        model = GEMINI_MODEL
        llm = Gemini(
            api_key=GOOGLE_API_KEY,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return llm, model


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
    provider: str = "gemini",
) -> LLMResponse:
    """
    Generate text via LLM, with caching and usage tracking.

    Args:
        prompt: The user/task prompt
        system: System instruction
        model: Model name override
        temperature: Sampling temperature
        max_tokens: Max output tokens
        json_mode: If True, hint the model to return JSON
        cache_key: Explicit cache key; if None, auto-derived
        ttl_s: Cache TTL in seconds
        provider: LLM provider ("gemini" | "openai" | "claude")

    Returns:
        LLMResponse with text, usage info, cache status
    """
    # Resolve model from provider if not explicitly set
    if not model:
        if provider == "openai":
            model = OPENAI_MODEL
        elif provider == "claude":
            model = ANTHROPIC_MODEL
        else:
            model = GEMINI_MODEL

    # ── Build cache key (includes provider) ──
    if cache_key is None:
        key_data = f"{provider}:{model}:{system[:200]}:{prompt}"
        cache_key = "llm:" + hashlib.sha256(key_data.encode()).hexdigest()[:32]

    # ── Check cache ──
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info(f"[LLMClient] Cache HIT ({provider}/{cache_key[:16]}...)")
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
                provider=provider,
            ),
        )

    # ── Create LLM ──
    llm, model = create_llm(provider, temperature, max_tokens)

    last_error = None
    for attempt in range(1 + LLM_MAX_RETRIES):
        try:
            start = time.time()

            # Use chat() for OpenAI/Claude (proper system prompt handling)
            if provider in ("openai", "claude") and system:
                from llama_index.core.llms import ChatMessage, MessageRole
                messages = [
                    ChatMessage(role=MessageRole.SYSTEM, content=system),
                    ChatMessage(role=MessageRole.USER, content=prompt),
                ]
                response = llm.chat(messages)
                text = response.message.content.strip()
            else:
                full_prompt = f"{system}\n\n{prompt}" if system else prompt
                response = llm.complete(full_prompt)
                text = response.text.strip()

            elapsed_ms = (time.time() - start) * 1000

            # ── Build usage ──
            prompt_tok = estimate_tokens((system + prompt) if system else prompt)
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
                provider=provider,
            )

            logger.info(
                f"[LLMClient] {provider}/{model} | {prompt_tok}+{comp_tok} tok | "
                f"${cost:.6f} | {elapsed_ms:.0f}ms"
            )

            # ── Cache result ──
            _cache_set(cache_key, text, ttl_s)

            return LLMResponse(text=text, usage=usage, raw=response)

        except Exception as e:
            last_error = e
            if attempt < LLM_MAX_RETRIES:
                wait = 2 ** attempt
                logger.warning(f"[LLMClient] {provider} retry {attempt+1} after {wait}s: {e}")
                time.sleep(wait)
            else:
                logger.error(f"[LLMClient] {provider} failed after {1 + LLM_MAX_RETRIES} attempts: {e}")

    raise RuntimeError(f"LLM call failed ({provider}): {last_error}")


def generate_json(
    prompt: str,
    *,
    system: str = "",
    model: str = "",
    cache_key: Optional[str] = None,
    ttl_s: int = CACHE_TTL_SECONDS,
    provider: str = "gemini",
) -> LLMResponse:
    """Generate text and parse as JSON. Raises on invalid JSON."""
    import re as _re

    resp = generate_text(
        prompt, system=system, model=model,
        json_mode=True, cache_key=cache_key, ttl_s=ttl_s,
        provider=provider,
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


# ── Dual-Provider API ────────────────────────────────────────

def generate_text_dual(
    prompt: str,
    *,
    system: str = "",
    temperature: float = 0.1,
    max_tokens: int = 2048,
    json_mode: bool = False,
    cache_key: Optional[str] = None,
    ttl_s: int = CACHE_TTL_SECONDS,
    providers: Optional[List[str]] = None,
) -> DualLLMResponse:
    """
    Generate text from both OpenAI and Claude in parallel.

    Args:
        prompt: The user/task prompt
        system: System instruction
        temperature: Sampling temperature
        max_tokens: Max output tokens
        json_mode: If True, hint the model to return JSON
        cache_key: Explicit cache key
        ttl_s: Cache TTL in seconds
        providers: List of providers (default: LLM_PROVIDERS)

    Returns:
        DualLLMResponse with results from each provider
    """
    providers = providers or LLM_PROVIDERS
    result = DualLLMResponse()

    def _call_provider(prov: str):
        try:
            resp = generate_text(
                prompt,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
                cache_key=f"{cache_key}:{prov}" if cache_key else None,
                ttl_s=ttl_s,
                provider=prov,
            )
            return prov, resp, None
        except Exception as e:
            logger.error(f"[LLMClient] {prov} failed in dual call: {e}")
            return prov, None, str(e)

    with ThreadPoolExecutor(max_workers=len(providers)) as executor:
        futures = [executor.submit(_call_provider, p) for p in providers]
        for future in as_completed(futures):
            prov, resp, error = future.result()
            if prov == "gemini":
                result.gemini = resp
                result.gemini_error = error
            elif prov == "openai":
                result.openai = resp
                result.openai_error = error
            elif prov == "claude":
                result.claude = resp
                result.claude_error = error

    return result
