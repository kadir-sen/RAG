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
    GOOGLE_API_KEY, GEMINI_MODEL, GEMINI_MODEL_LITE,
    OPENAI_API_KEY, OPENAI_MODEL,
    ANTHROPIC_API_KEY, ANTHROPIC_MODEL,
    LLM_PRICING, CACHE_DIR, CACHE_TTL_SECONDS, REDIS_URL,
    LLM_TIMEOUT_SECONDS, LLM_MAX_RETRIES, LLM_PROVIDERS,
    MAX_LLM_CALLS_PER_QUERY,
)
from .types import LLMUsage, LLMResponse, DualLLMResponse
from .logger import logger
from .usage_tracker import enforce_budget, record_usage


# Native google-genai SDK is required for Gemini extended thinking (the legacy
# llama-index Gemini wrapper can't pass thinking_config). It is optional: when
# absent, the Gemini thinking path degrades gracefully to the standard call.
try:
    import importlib.util as _ilu
    _GENAI_AVAILABLE = _ilu.find_spec("google.genai") is not None
except Exception:
    _GENAI_AVAILABLE = False


def _attribute_to_current_user(prompt_tok: int, comp_tok: int) -> None:
    """Mirror an LLM call to the active user's per-user counter.

    The active user (if any) is read from a contextvar populated by the FastAPI
    auth dependency. Background jobs and CLI runs leave it unset, in which case
    we only update the global tracker.
    """
    try:
        from backend.core.security import get_current_username
    except Exception:
        return
    username = get_current_username()
    if not username:
        return
    try:
        from .user_store import get_user_store

        get_user_store().increment_usage(username, prompt_tok, comp_tok)
    except Exception as exc:  # pragma: no cover — never break the request path
        logger.warning(f"[LLMClient] per-user usage record failed: {exc}")


def _enforce_user_quota() -> None:
    """If a user context is active, raise UserQuotaExceededError when capped."""
    try:
        from backend.core.security import get_current_username
    except Exception:
        return
    username = get_current_username()
    if not username:
        return
    try:
        from .user_store import get_user_store

        get_user_store().enforce_quota(username)
    except Exception:
        # enforce_quota raises UserQuotaExceededError on real cap hits — let it bubble
        raise

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


# ── Anthropic SDK Wrapper (no llama_index dependency) ────────

class _AnthropicCompletionResponse:
    """Mimics LlamaIndex CompletionResponse."""
    def __init__(self, text: str, output_tokens: int = 0, input_tokens: int = 0):
        self.text = text
        self.output_tokens = output_tokens
        self.input_tokens = input_tokens


class _AnthropicChatResponse:
    """Mimics LlamaIndex ChatResponse."""
    def __init__(self, text: str, output_tokens: int = 0, input_tokens: int = 0):
        self.message = type('Msg', (), {'content': text})()
        self.output_tokens = output_tokens
        self.input_tokens = input_tokens


def _anthropic_extract_text(resp) -> str:
    """Return the first text block, skipping any leading `thinking` block."""
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "text":
            return block.text
    # Fallback: legacy single-block responses
    try:
        return resp.content[0].text
    except Exception:
        return ""


class _AnthropicWrapper:
    """Thin wrapper around anthropic SDK matching LlamaIndex LLM interface.

    When ``thinking`` (a token budget) is set, extended thinking is enabled: the
    API requires temperature == 1, ``budget_tokens`` >= 1024 and < max_tokens, and
    the response carries a leading `thinking` block that must be skipped.
    """

    def __init__(self, api_key: str, model: str, temperature: float = 0.1,
                 max_tokens: int = 2048, thinking: int = 0):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.thinking = int(thinking) if thinking else 0
        # Extended thinking requires temperature == 1 and headroom above the budget.
        if self.thinking > 0:
            self.temperature = 1.0
            self.max_tokens = max(max_tokens, self.thinking + 512)
        else:
            self.temperature = temperature
            self.max_tokens = max_tokens

    def _thinking_kwargs(self) -> dict:
        if self.thinking > 0:
            budget = max(1024, self.thinking)
            return {"thinking": {"type": "enabled", "budget_tokens": budget}}
        return {}

    def complete(self, prompt: str):
        import anthropic
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=[{"role": "user", "content": prompt}],
                **self._thinking_kwargs(),
            )
            text = _anthropic_extract_text(resp)
            u = getattr(resp, "usage", None)
            return _AnthropicCompletionResponse(
                text,
                output_tokens=getattr(u, "output_tokens", 0) or 0,
                input_tokens=getattr(u, "input_tokens", 0) or 0,
            )
        except anthropic.BadRequestError:
            raise  # content policy — do not retry
        except anthropic.AuthenticationError:
            raise  # auth error — do not retry

    def chat(self, messages):
        import anthropic
        api_messages = []
        system_text = ""
        for m in messages:
            role = getattr(m, 'role', 'user')
            content = getattr(m, 'content', str(m))
            role_str = str(role).lower().replace('messageRole.', '').replace('messagerole.', '')
            if role_str == 'system':
                system_text = content
            else:
                api_messages.append({"role": role_str, "content": content})
        kwargs = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=api_messages,
            **self._thinking_kwargs(),
        )
        if system_text:
            kwargs["system"] = system_text
        try:
            resp = self.client.messages.create(**kwargs)
            text = _anthropic_extract_text(resp)
            u = getattr(resp, "usage", None)
            return _AnthropicChatResponse(
                text,
                output_tokens=getattr(u, "output_tokens", 0) or 0,
                input_tokens=getattr(u, "input_tokens", 0) or 0,
            )
        except anthropic.BadRequestError:
            raise  # content policy — do not retry
        except anthropic.AuthenticationError:
            raise  # auth error — do not retry


# ── LLM Factory ─────────────────────────────────────────────

def _gemini_generate_thinking(
    prompt: str, system: str, temperature: float, max_tokens: int,
    model: str, thinking_budget: int,
):
    """Native google-genai call with extended thinking for Gemini 2.5.

    The legacy llama-index Gemini wrapper cannot pass thinking_config, so this
    bypasses it. Returns (text, completion_tokens, thoughts_tokens).
    """
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GOOGLE_API_KEY)
    contents = f"{system}\n\n{prompt}" if system else prompt
    resp = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            thinking_config=types.ThinkingConfig(thinking_budget=int(thinking_budget)),
        ),
    )
    text = (resp.text or "").strip()
    comp_tok = 0
    thoughts_tok = 0
    um = getattr(resp, "usage_metadata", None)
    if um is not None:
        comp_tok = getattr(um, "candidates_token_count", 0) or 0
        thoughts_tok = getattr(um, "thoughts_token_count", 0) or 0
    return text, comp_tok, thoughts_tok


def create_llm(provider: str, temperature: float = 0.1, max_tokens: int = 2048,
               thinking: int = 0, model: str = ""):
    """
    Create a LlamaIndex LLM instance for the given provider.

    Args:
        provider: "openai" | "claude" | "gemini"
        temperature: Sampling temperature
        max_tokens: Max output tokens
        thinking: Extended-thinking token budget (Claude only here; the Gemini
            thinking path bypasses create_llm via _gemini_generate_thinking).
        model: Optional model override. When empty, the provider default is used.
            This is how the cheap tier (GEMINI_MODEL_LITE) is selected per call —
            previously the gemini branch hardcoded GEMINI_MODEL and ignored any
            override, so model tiering silently never took effect.

    Returns:
        Tuple of (llm_instance, model_name)
    """
    if provider == "openai":
        from llama_index.llms.openai import OpenAI
        model = model or OPENAI_MODEL
        llm = OpenAI(
            api_key=OPENAI_API_KEY,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return llm, model
    elif provider == "claude":
        model = model or ANTHROPIC_MODEL
        llm = _AnthropicWrapper(
            api_key=ANTHROPIC_API_KEY,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            thinking=thinking,
        )
        return llm, model
    else:
        from llama_index.llms.gemini import Gemini
        model = model or GEMINI_MODEL
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
    thinking: int = 0,
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
        thinking: Extended-thinking/reasoning token budget. 0 = off (default).
            Honoured for gemini (native google-genai path) and claude; no-op for
            openai (gpt-4o-mini has no thinking knob).

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

    thinking = int(thinking) if thinking else 0
    # Gemini thinking needs the native google-genai SDK; degrade gracefully if absent.
    use_gemini_thinking = (provider == "gemini" and thinking > 0 and _GENAI_AVAILABLE)
    if provider == "gemini" and thinking > 0 and not _GENAI_AVAILABLE:
        logger.warning(
            "[LLMClient] thinking requested for gemini but google-genai not installed "
            "— proceeding without thinking (pip install google-genai to enable)"
        )
    use_claude_thinking = (provider == "claude" and thinking > 0)

    # ── Build cache key (includes provider + thinking budget) ──
    if cache_key is None:
        key_data = f"{provider}:{model}:think{thinking}:{system[:200]}:{prompt}"
        cache_key = "llm:" + hashlib.sha256(key_data.encode()).hexdigest()[:32]
    elif thinking > 0:
        # Explicit caller keys must still differ by thinking budget.
        cache_key = f"{cache_key}:think{thinking}"

    # ── Enforce global + per-user usage caps (cache hits still allowed below) ──
    enforce_budget()
    _enforce_user_quota()

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

    # ── Soft per-query budget (degrade, never block) ──
    # Cache hits above are always free and already returned. For a real call,
    # if this query has already burned MAX_LLM_CALLS_PER_QUERY non-cache calls,
    # force the cheap tier + no thinking instead of dropping the answer. This
    # bleeds cost out of runaway/pathological queries without losing correctness
    # on normal multi-step ones (the default budget is generous).
    try:
        from .telemetry import get_current_trace
        _tr = get_current_trace()
        if _tr is not None:
            _real_calls = max(0, _tr.llm_calls - _tr.cache_hits)
            if _real_calls >= MAX_LLM_CALLS_PER_QUERY and provider == "gemini":
                if model != GEMINI_MODEL_LITE or thinking:
                    logger.warning(
                        f"[LLMClient] soft budget hit ({_real_calls} calls) — "
                        f"degrading to {GEMINI_MODEL_LITE}, thinking=0"
                    )
                    if "budget_soft_cap" not in _tr.errors:
                        _tr.record_error("budget_soft_cap")
                model = GEMINI_MODEL_LITE
                thinking = 0
                use_gemini_thinking = False
                use_claude_thinking = False
    except Exception:
        pass

    # ── Create LLM (skipped for the native gemini-thinking path) ──
    if use_gemini_thinking:
        llm = None
    else:
        llm, model = create_llm(
            provider, temperature, max_tokens,
            thinking=thinking if use_claude_thinking else 0,
            model=model,
        )

    last_error = None
    for attempt in range(1 + LLM_MAX_RETRIES):
        try:
            start = time.time()
            thoughts_tok = 0
            native_comp_tok = 0

            if use_gemini_thinking:
                # Native google-genai path (legacy llama-index wrapper can't do thinking)
                text, native_comp_tok, thoughts_tok = _gemini_generate_thinking(
                    prompt=prompt, system=system,
                    temperature=temperature, max_tokens=max_tokens,
                    model=model, thinking_budget=thinking,
                )
                text = text.strip()
                response = None
            # Use chat() for OpenAI/Claude (proper system prompt handling)
            elif provider in ("openai", "claude") and system:
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

            # ── Build usage (thinking tokens are billed as output tokens) ──
            prompt_tok = estimate_tokens((system + prompt) if system else prompt)
            if native_comp_tok:
                comp_tok = native_comp_tok + thoughts_tok
            else:
                # Claude exposes real output_tokens (incl. thinking) on the response.
                resp_out = getattr(response, "output_tokens", 0) or 0
                comp_tok = resp_out if resp_out else estimate_tokens(text)
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

            # ── Record into global + per-user usage trackers ──
            try:
                record_usage(prompt_tok, comp_tok, cost)
            except Exception as track_err:
                logger.warning(f"[LLMClient] usage tracker failed: {track_err}")
            _attribute_to_current_user(prompt_tok, comp_tok)

            return LLMResponse(text=text, usage=usage, raw=response)

        except Exception as e:
            last_error = e
            # Check for non-retryable errors (content policy, auth)
            _non_retryable = False
            try:
                import anthropic
                if isinstance(e, (anthropic.BadRequestError, anthropic.AuthenticationError)):
                    _non_retryable = True
            except ImportError:
                pass
            try:
                import openai as _openai
                if isinstance(e, _openai.AuthenticationError):
                    _non_retryable = True
            except ImportError:
                pass

            if _non_retryable:
                logger.error(f"[LLMClient] {provider} non-retryable error: {e}")
                break

            if attempt < LLM_MAX_RETRIES:
                # Longer backoff for rate limit errors
                _is_rate_limit = False
                try:
                    import anthropic
                    _is_rate_limit = isinstance(e, anthropic.RateLimitError)
                except ImportError:
                    pass
                wait = (2 ** attempt * 5) if _is_rate_limit else (2 ** attempt)
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
    thinking: int = 0,
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
                thinking=thinking,
            )
            return prov, resp, None
        except Exception as e:
            logger.error(f"[LLMClient] {prov} failed in dual call: {e}")
            return prov, None, str(e)

    # Propagate the caller's contextvars (active user) into worker threads
    # so per-user usage attribution and quota enforcement still apply.
    import contextvars as _ctxvars
    _ctx = _ctxvars.copy_context()

    with ThreadPoolExecutor(max_workers=len(providers)) as executor:
        futures = [executor.submit(_ctx.run, _call_provider, p) for p in providers]
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
