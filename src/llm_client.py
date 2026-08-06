"""
Unified LLM client with caching, cost tracking, retries, and timeouts.
Supports multiple providers: Gemini, OpenAI, Claude (Anthropic).
All LLM calls in the system should go through this module.
"""
import hashlib
import json
import time
import random
import uuid
from contextvars import ContextVar
from decimal import Decimal, ROUND_HALF_UP
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from .config import (
    GEMINI_MODEL, GEMINI_MODEL_LITE, GEMINI_INGESTION_MODEL,
    OPENAI_API_KEY, OPENAI_MODEL,
    ANTHROPIC_API_KEY, ANTHROPIC_MODEL,
    LLM_PRICING, CACHE_DIR, CACHE_TTL_SECONDS, REDIS_URL,
    LLM_TIMEOUT_SECONDS, LLM_MAX_RETRIES, LLM_PROVIDERS,
    MAX_LLM_CALLS_PER_QUERY,
)
from .types import LLMUsage, LLMResponse, DualLLMResponse
from .logger import logger
from .usage_tracker import enforce_budget, record_usage
from .model_profiles import clamp_output_tokens, get_task_profile
from .provider_credentials import get_google_api_key, google_credential_scope


# Native google-genai SDK is required for Gemini extended thinking (the legacy
# llama-index Gemini wrapper can't pass thinking_config). It is optional: when
# absent, the Gemini thinking path degrades gracefully to the standard call.
try:
    import importlib.util as _ilu
    _GENAI_AVAILABLE = _ilu.find_spec("google.genai") is not None
except Exception:
    _GENAI_AVAILABLE = False


class BillingRecordingError(RuntimeError):
    """A provider call succeeded but its durable user charge could not be stored."""


class LLMIncompleteResponseError(RuntimeError):
    """The provider stopped before producing a complete response."""


class LLMInvalidStructuredOutputError(RuntimeError):
    """A structured response failed syntactic or schema validation."""


class LLMInputBudgetExceededError(RuntimeError):
    """The task input exceeds its deliberate profile budget."""


class LLMResearchBudgetExceededError(RuntimeError):
    """A chronology exhausted its bounded number of provider calls."""


chronology_call_limit_var: ContextVar[int] = ContextVar(
    "chronology_call_limit", default=40,
)
chronology_call_count_var: ContextVar[int] = ContextVar(
    "chronology_call_count", default=0,
)
chronology_budget_active_var: ContextVar[bool] = ContextVar(
    "chronology_budget_active", default=False,
)


def _google_api_key() -> str:
    """Resolve the active user's server-side key without exposing it to callers."""
    return get_google_api_key()


def begin_chronology_call_budget(limit: int = 40) -> None:
    chronology_call_count_var.set(0)
    chronology_call_limit_var.set(max(1, min(40, int(limit))))
    chronology_budget_active_var.set(True)


def set_chronology_call_budget(limit: int) -> None:
    chronology_call_limit_var.set(max(1, min(40, int(limit))))


def end_chronology_call_budget() -> None:
    chronology_budget_active_var.set(False)
    chronology_call_count_var.set(0)


def _attribute_to_current_user(
    prompt_tok: int, comp_tok: int, *, provider: str = "", model: str = "",
    reasoning_tokens: int = 0, cached_tokens: int = 0, cost_nanos: int = 0,
    usage_source: str = "provider", task_type: str = "generation",
    count_legacy_tokens: bool = True,
) -> None:
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

        store = get_user_store()
        if count_legacy_tokens:
            store.increment_usage(username, prompt_tok, comp_tok)
        if provider and model:
            try:
                from .project_context import get_current_project_id
                from .run_store import current_run_id_var
                store.billing.record_charge(
                    username=username,
                    project_id=get_current_project_id(),
                    run_id=current_run_id_var.get(),
                    job_id=current_run_id_var.get(),
                    task_type=task_type,
                    provider=provider,
                    model=model,
                    prompt_tokens=prompt_tok,
                    # Provider metadata reports visible output and thinking
                    # separately. ``comp_tok`` is the billable total used by
                    # the legacy counter, while the ledger keeps the two
                    # dimensions distinct for admin reporting.
                    completion_tokens=max(0, comp_tok - reasoning_tokens),
                    reasoning_tokens=reasoning_tokens,
                    cached_tokens=cached_tokens,
                    provider_cost_nanos=cost_nanos,
                    usage_source=usage_source,
                    idempotency_key=f"llm:{uuid.uuid4().hex}",
                )
            except Exception as billing_exc:
                logger.error(f"[LLMClient] billing ledger write failed: {billing_exc}")
                raise
    except Exception as exc:
        logger.error(f"[LLMClient] per-user usage record failed: {exc}")
        raise BillingRecordingError(str(exc)) from exc


def _record_run_usage(usage: LLMUsage) -> None:
    try:
        from .run_store import get_run_store
        get_run_store().record_llm(usage)
    except Exception as exc:
        logger.debug(f"[LLMClient] run usage record skipped: {exc}")


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

        store = get_user_store()
        account = store.billing.get_account(username)
        if account and account.get("plan_type") == "demo":
            store.billing.enforce_credits(username)
        else:
            store.enforce_quota(username)
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


def _cache_delete(key: str) -> bool:
    cache = _get_cache()
    if cache is None:
        return False
    try:
        if hasattr(cache, "delete"):
            return bool(cache.delete(key))
        if isinstance(cache, dict):
            return cache.pop(key, None) is not None
    except Exception:
        pass
    return False


def cache_keys() -> List[str]:
    """Best-effort key listing used only by the targeted cleanup CLI."""
    cache = _get_cache()
    try:
        if hasattr(cache, "iterkeys"):
            return [str(key) for key in cache.iterkeys()]
        if hasattr(cache, "scan_iter"):
            return [key.decode() if isinstance(key, bytes) else str(key)
                    for key in cache.scan_iter(match="*")]
        if isinstance(cache, dict):
            return [str(key) for key in cache]
    except Exception:
        pass
    return []


def delete_cache_key(key: str) -> bool:
    return _cache_delete(key)


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

def _gemini_generate_native(
    prompt: str, system: str, max_tokens: int, model: str,
    thinking_level: str = "medium", json_mode: bool = False,
    response_schema: Optional[Dict[str, Any]] = None,
    timeout_seconds: int = 120,
):
    """Native Gemini call with authoritative usage metadata.

    Gemini 3 uses thinking levels.  The upload-only Gemini 2.5 Flash-Lite
    policy disables thinking with a zero budget so metadata/OCR work does not
    accidentally spend output-priced reasoning tokens.
    """
    from google import genai
    from google.genai import types

    try:
        client = genai.Client(
            api_key=_google_api_key(),
            http_options=types.HttpOptions(timeout=max(1, timeout_seconds) * 1000),
        )
    except (AttributeError, TypeError):
        client = genai.Client(api_key=_google_api_key())
    thinking_config = (
        types.ThinkingConfig(thinking_budget=0)
        if model.removeprefix("models/").startswith("gemini-2.5-")
        else types.ThinkingConfig(thinking_level=thinking_level)
    )
    config_kwargs: Dict[str, Any] = {
        "max_output_tokens": max_tokens,
        "thinking_config": thinking_config,
    }
    if system:
        config_kwargs["system_instruction"] = system
    if json_mode or response_schema:
        config_kwargs["response_mime_type"] = "application/json"
    if response_schema:
        config_kwargs["response_json_schema"] = _gemini_compatible_response_schema(
            response_schema
        )
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(**config_kwargs),
    )
    text = (resp.text or "").strip()
    comp_tok = 0
    thoughts_tok = 0
    um = getattr(resp, "usage_metadata", None)
    prompt_tok = 0
    cached_tok = 0
    if um is not None:
        prompt_tok = getattr(um, "prompt_token_count", 0) or 0
        comp_tok = getattr(um, "candidates_token_count", 0) or 0
        thoughts_tok = getattr(um, "thoughts_token_count", 0) or 0
        cached_tok = getattr(um, "cached_content_token_count", 0) or 0
    return text, prompt_tok, comp_tok, thoughts_tok, cached_tok, resp


def _gemini_compatible_response_schema(value: Any) -> Any:
    """Return the schema subset accepted by Gemini structured output.

    Gemini accepts array cardinality constraints in shallow schemas, but its
    grammar compiler rejects otherwise valid Pydantic schemas when nested
    object arrays carry ``minItems``/``maxItems``.  The complete schema is
    still enforced by ``validation_model`` after generation, so removing only
    those provider-side grammar hints does not weaken COAir validation.
    """
    if isinstance(value, list):
        return [_gemini_compatible_response_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: _gemini_compatible_response_schema(item)
        for key, item in value.items()
        if key not in {"minItems", "maxItems"}
    }


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
        model: Optional model override. Central policy in generate_text resolves
            the final model before this factory is called.

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

        def _mk(m: str):
            kwargs = {"api_key": _google_api_key(), "model": m,
                      "max_tokens": max_tokens}
            # Gemini 3.5/3.6 removed sampling parameters. Passing a legacy
            # temperature causes a request-level validation error on the GA IDs.
            if not model.startswith(("gemini-3.5", "gemini-3.6")):
                kwargs["temperature"] = temperature
            return Gemini(**kwargs)

        # Some llama-index/google-generativeai versions require a "models/" prefix
        # and reject the bare name ("Model names should start with `models/`").
        # Try as-is, then with the prefix — robust across versions. A bare-name
        # rejection here otherwise fails the call, burns a retry, and (via an unset
        # Settings.llm) lets LlamaIndex silently fall back to OpenAI. Keep the
        # ORIGINAL name for cost/cache; only the wrapper sees the prefixed form.
        try:
            llm = _mk(model)
        except Exception as e:
            if "models/" in str(e) and not model.startswith(("models/", "tunedModels/")):
                logger.info(f"[LLMClient] gemini wrapper wants prefixed name → models/{model}")
                llm = _mk(f"models/{model}")
            else:
                raise
        return llm, model


# ── Cost Estimation ──────────────────────────────────────────

def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int,
                  cached_tokens: int = 0) -> float:
    """Estimate cost in USD for a given call."""
    return estimate_cost_nanos(model, prompt_tokens, completion_tokens, cached_tokens) / 1_000_000_000


def estimate_cost_nanos(model: str, prompt_tokens: int, completion_tokens: int,
                        cached_tokens: int = 0) -> int:
    """Price a call using the explicit catalog; unknown models fail closed."""
    pricing = LLM_PRICING.get(model)
    if not pricing:
        raise ValueError(f"No pricing configured for model: {model}")
    cached_tokens = max(0, min(int(cached_tokens or 0), int(prompt_tokens or 0)))
    uncached_tokens = max(0, int(prompt_tokens or 0) - cached_tokens)
    value = (
        Decimal(uncached_tokens) / Decimal(1_000_000) * Decimal(str(pricing["input"]))
        + Decimal(cached_tokens) / Decimal(1_000_000)
        * Decimal(str(pricing.get("cached_input", pricing["input"])))
        + Decimal(max(0, int(completion_tokens))) / Decimal(1_000_000)
        * Decimal(str(pricing["output"]))
    )
    return int((value * Decimal(1_000_000_000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def estimate_tokens(text: str) -> int:
    """Rough token estimate (chars / 4)."""
    return max(1, len(text) // 4)


def count_input_tokens(model: str, text: str) -> int:
    """Use Gemini count_tokens when available, with a deterministic fallback."""
    estimate = estimate_tokens(text)
    if not model.startswith((
        "gemini-2.5-", "models/gemini-2.5-", "gemini-3.", "models/gemini-3.",
    )):
        return estimate
    try:
        from google import genai
        client = genai.Client(api_key=_google_api_key())
        result = client.models.count_tokens(model=model, contents=text)
        return int(getattr(result, "total_tokens", 0) or estimate)
    except Exception as exc:
        logger.debug(f"[LLMClient] count_tokens fallback: {exc}")
        return estimate


def _current_model_policy() -> str:
    try:
        from backend.core.security import get_current_username
        from .user_store import get_user_store
        username = get_current_username()
        account = get_user_store().billing.get_account(username) if username else None
        return str((account or {}).get("model_policy") or "")
    except Exception:
        return ""


def _demo_thinking_level(task_type: str, requested_model: str) -> str:
    task = (task_type or "").lower()
    if requested_model == GEMINI_MODEL_LITE or any(x in task for x in (
        "classif", "metadata", "scope", "ocr", "verify", "extract",
    )):
        return "minimal"
    if any(x in task for x in ("plan", "rerank", "research")):
        return "low"
    return "medium"


_INGESTION_TASKS = {
    "ocr", "metadata", "ingestion_metadata", "ingestion_notice_metadata",
    "ingestion_cluster_label", "ingestion_classification",
}


def _is_ingestion_task(task_type: str) -> bool:
    task = (task_type or "").strip().lower()
    return task.startswith("ingestion_") or task in _INGESTION_TASKS


def _model_for_task(task_type: str) -> str:
    """Keep user research on 3.6; reserve the cheap model for file ingestion."""
    return GEMINI_INGESTION_MODEL if _is_ingestion_task(task_type) else "gemini-3.6-flash"


def effective_providers(providers: List[str]) -> List[str]:
    """Production quality policy is Gemini-only; never fan out duplicate calls."""
    return ["gemini"]


# ── Core API ─────────────────────────────────────────────────

def generate_text(
    prompt: str,
    *,
    system: str = "",
    model: str = "",
    temperature: float = 0.1,
    max_tokens: Optional[int] = None,
    json_mode: bool = False,
    cache_key: Optional[str] = None,
    ttl_s: int = CACHE_TTL_SECONDS,
    provider: str = "gemini",
    thinking: int = 0,
    thinking_level: str = "",
    task_type: str = "generation",
    response_schema: Optional[Dict[str, Any]] = None,
    timeout_seconds: Optional[int] = None,
    prompt_version: str = "",
    cache_context: str = "",
    cache_validator=None,
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
    requested_model = model
    profile = get_task_profile(task_type)
    # Query entry points set this request-local value once.  Appending the
    # compact terminology block here makes planner, SQL, RAG synthesis and
    # report calls share the same glossary without changing the original text
    # used by intent routing or conversation history.
    try:
        from .jargon_manager import current_prepared_query_var
        prepared = current_prepared_query_var.get()
        if prepared and prepared.context and prepared.context not in system:
            system = f"{system}\n\n{prepared.context}".strip()
    except Exception:
        pass
    # System-wide model boundary: every interactive/research call uses the
    # quality model. Only explicitly tagged upload processing may use the cheap
    # tier. This also closes legacy OpenAI/Claude and Lite fallback paths.
    provider = "gemini"
    model = _model_for_task(task_type)
    thinking_level = thinking_level or (
        "minimal" if _is_ingestion_task(task_type)
        else _demo_thinking_level(task_type, requested_model)
    )

    # Resolve model from provider if not explicitly set
    if not model:
        if provider == "openai":
            model = OPENAI_MODEL
        elif provider == "claude":
            model = ANTHROPIC_MODEL
        else:
            model = GEMINI_MODEL

    if model not in LLM_PRICING:
        raise ValueError(f"No pricing configured for model: {model}")

    max_tokens = clamp_output_tokens(model, max_tokens or profile.max_output_tokens, profile)
    timeout_seconds = int(timeout_seconds or profile.timeout_seconds)

    thinking = int(thinking) if thinking else 0
    if not thinking_level:
        thinking_level = profile.thinking_level if provider == "gemini" else (
            "medium" if thinking else "minimal"
        )
    # Gemini thinking needs the native google-genai SDK; degrade gracefully if absent.
    use_native_gemini = (
        provider == "gemini" and _GENAI_AVAILABLE
        and model.startswith((
            "gemini-2.5-", "models/gemini-2.5-", "gemini-3.", "models/gemini-3.",
        ))
    )
    use_gemini_thinking = (provider == "gemini" and thinking > 0 and _GENAI_AVAILABLE)
    if provider == "gemini" and thinking > 0 and not _GENAI_AVAILABLE:
        logger.warning(
            "[LLMClient] thinking requested for gemini but google-genai not installed "
            "— proceeding without thinking (pip install google-genai to enable)"
        )
    use_claude_thinking = (provider == "claude" and thinking > 0)

    # ── Build cache key (includes provider + thinking budget) ──
    namespace = (cache_key or f"llm:{task_type}").split(":", 1)[0]
    key_data = json.dumps({
        "cache_version": 2,
        "provider": provider, "model": model, "thinking": thinking,
        "thinking_level": thinking_level, "task_type": task_type,
        "max_tokens": max_tokens, "prompt_version": prompt_version,
        "system": system, "prompt": prompt, "schema": response_schema,
        "context": cache_context,
        # Do not share cached provider responses across a dedicated-key user
        # and the global account. This contains only an alias, never the key.
        "credential_scope": google_credential_scope(),
    }, ensure_ascii=False, sort_keys=True, default=str)
    cache_key = f"{namespace}:v2:" + hashlib.sha256(key_data.encode()).hexdigest()

    # ── Enforce global + per-user usage caps (cache hits still allowed below) ──
    enforce_budget()
    _enforce_user_quota()

    # ── Check cache ──
    cache_enabled = int(ttl_s) > 0
    cached = _cache_get(cache_key) if cache_enabled else None
    if cached is not None:
        if cache_validator is not None and not cache_validator(cached):
            logger.warning(f"[LLMClient] deleting invalid cache entry {cache_key[:24]}...")
            _cache_delete(cache_key)
            cached = None
    if cached is not None:
        logger.info(f"[LLMClient] Cache HIT ({provider}/{cache_key[:16]}...)")
        prompt_tok = estimate_tokens(prompt + system)
        comp_tok = estimate_tokens(cached)
        cached_usage = LLMUsage(
            prompt_tokens=prompt_tok,
            completion_tokens=comp_tok,
            total_tokens=prompt_tok + comp_tok,
            cost_estimate=0.0,
            model=model,
            latency_ms=0.0,
            cache_hit=True,
            provider=provider,
            cached_tokens=prompt_tok,
            task_type=task_type,
            finish_reason="CACHE",
        )
        _record_run_usage(cached_usage)
        _attribute_to_current_user(
            prompt_tok, comp_tok, provider=provider, model=model,
            cached_tokens=prompt_tok, cost_nanos=0, usage_source="cache",
            task_type=task_type, count_legacy_tokens=False,
        )
        return LLMResponse(
            text=cached,
            usage=cached_usage,
            finish_reason="CACHE",
        )

    combined_input = f"{system}\n\n{prompt}" if system else prompt
    estimated_input = estimate_tokens(combined_input)
    exact_input = (
        count_input_tokens(model, combined_input)
        if task_type.startswith("chronology_") or estimated_input >= profile.max_input_tokens * .8
        else estimated_input
    )
    if exact_input > profile.max_input_tokens:
        raise LLMInputBudgetExceededError(
            f"input_budget_exceeded:{task_type}:{exact_input}>{profile.max_input_tokens}"
        )

    # ── Soft per-query budget (reduce thinking, never downgrade/block) ──
    # Cache hits above are always free and already returned. For a real call,
    # if this query has already burned MAX_LLM_CALLS_PER_QUERY non-cache calls,
    # reduce thinking without switching away from the task's selected model.
    try:
        from .telemetry import get_current_trace
        _tr = get_current_trace()
        if _tr is not None:
            _real_calls = max(0, _tr.llm_calls - _tr.cache_hits)
            if (not chronology_budget_active_var.get()
                    and _real_calls >= MAX_LLM_CALLS_PER_QUERY and provider == "gemini"
                    and task_type != "report_structured"):
                if thinking_level != "minimal" or thinking:
                    logger.warning(
                        f"[LLMClient] soft budget hit ({_real_calls} calls) — "
                        f"keeping {model} and reducing thinking to minimal"
                    )
                    if "budget_soft_cap" not in _tr.errors:
                        _tr.record_error("budget_soft_cap")
                # Never downgrade a user query to a weaker model. Reduce only
                # thinking after the soft call budget; ingestion remains on its
                # explicitly selected cheap model.
                model = _model_for_task(task_type)
                thinking_level = "minimal"
                thinking = 0
                use_gemini_thinking = False
                use_claude_thinking = False
    except Exception:
        pass

    # ── Create LLM (skipped for the native gemini-thinking path) ──
    if use_native_gemini or use_gemini_thinking:
        llm = None
    else:
        llm, model = create_llm(
            provider, temperature, max_tokens,
            thinking=thinking if use_claude_thinking else 0,
            model=model,
        )

    last_error = None
    retry_count = max(int(LLM_MAX_RETRIES), int(profile.provider_retries))
    for attempt in range(1 + retry_count):
        try:
            if chronology_budget_active_var.get():
                call_count = chronology_call_count_var.get()
                if call_count >= chronology_call_limit_var.get():
                    raise LLMResearchBudgetExceededError("research_budget_exhausted")
                chronology_call_count_var.set(call_count + 1)
            start = time.time()
            thoughts_tok = 0
            native_comp_tok = 0
            native_prompt_tok = 0
            native_cached_tok = 0

            if use_native_gemini or use_gemini_thinking:
                text, native_prompt_tok, native_comp_tok, thoughts_tok, native_cached_tok, response = _gemini_generate_native(
                    prompt=prompt, system=system, max_tokens=max_tokens,
                    model=model, thinking_level=thinking_level,
                    json_mode=json_mode, response_schema=response_schema,
                    timeout_seconds=timeout_seconds,
                )
                text = text.strip()
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
            prompt_tok = native_prompt_tok or estimate_tokens((system + prompt) if system else prompt)
            cached_tok = 0
            if native_comp_tok:
                comp_tok = native_comp_tok + thoughts_tok
            else:
                # Claude exposes real output_tokens (incl. thinking) on the response.
                resp_out = getattr(response, "output_tokens", 0) or 0
                comp_tok = resp_out if resp_out else estimate_tokens(text)
                # LlamaIndex keeps the provider response under .raw. Prefer
                # Google's authoritative usage metadata over character estimates.
                raw = getattr(response, "raw", None)
                meta = getattr(raw, "usage_metadata", None)
                if meta is None and isinstance(raw, dict):
                    meta = raw.get("usage_metadata") or raw.get("usageMetadata")
                if meta is not None:
                    def _usage_value(*names):
                        for name in names:
                            value = (meta.get(name) if isinstance(meta, dict)
                                     else getattr(meta, name, None))
                            if value is not None:
                                return int(value or 0)
                        return 0
                    prompt_tok = _usage_value("prompt_token_count", "promptTokenCount") or prompt_tok
                    candidates = _usage_value("candidates_token_count", "candidatesTokenCount")
                    thoughts_tok = _usage_value("thoughts_token_count", "thoughtsTokenCount")
                    cached_tok = _usage_value(
                        "cached_content_token_count", "cachedContentTokenCount"
                    )
                    if candidates or thoughts_tok:
                        comp_tok = candidates + thoughts_tok
            cached_tok = native_cached_tok or cached_tok
            visible_comp_tok = max(0, comp_tok - thoughts_tok)
            usage_source = "provider" if native_prompt_tok or getattr(response, "raw", None) else "estimated"
            cost_nanos = estimate_cost_nanos(model, prompt_tok, comp_tok, cached_tok)
            cost = cost_nanos / 1_000_000_000

            usage = LLMUsage(
                prompt_tokens=prompt_tok,
                completion_tokens=visible_comp_tok,
                total_tokens=prompt_tok + visible_comp_tok + thoughts_tok,
                cost_estimate=cost,
                model=model,
                latency_ms=round(elapsed_ms, 1),
                cache_hit=False,
                provider=provider,
                reasoning_tokens=thoughts_tok,
                cached_tokens=cached_tok,
                task_type=task_type,
            )

            logger.info(
                f"[LLMClient] {provider}/{model} | {prompt_tok}+{comp_tok} tok | "
                f"${cost:.6f} | {elapsed_ms:.0f}ms"
            )

            finish_reason = ""
            try:
                value = response.candidates[0].finish_reason
                finish_reason = str(getattr(value, "name", value) or "").upper()
                if "." in finish_reason:
                    finish_reason = finish_reason.rsplit(".", 1)[-1]
            except Exception:
                pass
            usage.finish_reason = finish_reason or "STOP"

            cacheable = bool(text)
            if finish_reason and finish_reason not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
                cacheable = False
            if cache_validator is not None and not cache_validator(text):
                cacheable = False

            # ── Cache result ──
            if cacheable and cache_enabled:
                _cache_set(cache_key, text, ttl_s)

            # ── Record into global + per-user usage trackers ──
            try:
                record_usage(prompt_tok, comp_tok, cost)
            except Exception as track_err:
                logger.warning(f"[LLMClient] usage tracker failed: {track_err}")
            _attribute_to_current_user(
                prompt_tok, comp_tok, provider=provider, model=model,
                reasoning_tokens=thoughts_tok, cached_tokens=cached_tok,
                cost_nanos=cost_nanos, usage_source=usage_source,
                task_type=task_type,
            )
            _record_run_usage(usage)

            if finish_reason == "MAX_TOKENS":
                raise LLMIncompleteResponseError("model_output_incomplete")
            if finish_reason and finish_reason not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
                raise LLMIncompleteResponseError(f"model_finish_{finish_reason.lower()}")
            if not cacheable:
                raise LLMInvalidStructuredOutputError("model_output_invalid")

            return LLMResponse(
                text=text, usage=usage, raw=response, finish_reason=finish_reason or "STOP",
            )

        except Exception as e:
            last_error = e
            # Check for non-retryable errors (content policy, auth)
            _non_retryable = False
            if isinstance(e, BillingRecordingError):
                _non_retryable = True
            if isinstance(e, LLMIncompleteResponseError):
                _non_retryable = True
            if isinstance(e, LLMResearchBudgetExceededError):
                _non_retryable = True
            error_text = str(e).casefold()
            if any(marker in error_text for marker in (
                "authentication", "unauthorized", "permission denied", "billing",
                "safety", "schema rejection", "invalid response schema",
                "invalid_argument", "invalid argument",
            )) and "429" not in error_text:
                _non_retryable = True
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

            if attempt < retry_count:
                # Longer backoff for rate limit errors
                _is_rate_limit = False
                try:
                    import anthropic
                    _is_rate_limit = isinstance(e, anthropic.RateLimitError)
                except ImportError:
                    pass
                wait = ((2 ** attempt * 5) if _is_rate_limit else (2 ** attempt))
                wait += random.uniform(0, min(1.0, wait * .2))
                logger.warning(f"[LLMClient] {provider} retry {attempt+1} after {wait}s: {e}")
                time.sleep(wait)
            else:
                logger.error(f"[LLMClient] {provider} failed after {1 + retry_count} attempts: {e}")

    if isinstance(last_error, (
        LLMIncompleteResponseError, LLMInvalidStructuredOutputError,
        LLMResearchBudgetExceededError,
    )):
        raise last_error
    raise RuntimeError(f"LLM call failed ({provider}): {last_error}")


def _schema_accepts(value: Any, schema: Optional[Dict[str, Any]]) -> bool:
    """Validate the JSON-schema subset supported by Gemini structured output."""
    if not schema:
        return True
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            return False
        if any(key not in value for key in schema.get("required", [])):
            return False
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and any(
            key not in properties for key in value
        ):
            return False
        return all(
            key not in value or _schema_accepts(value[key], sub)
            for key, sub in properties.items()
        )
    if expected == "array":
        if not isinstance(value, list):
            return False
        if len(value) < int(schema.get("minItems", 0)):
            return False
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            return False
        return all(_schema_accepts(item, schema.get("items")) for item in value)
    if expected == "string" and not isinstance(value, str):
        return False
    if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        return False
    if expected == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        return False
    if expected == "boolean" and not isinstance(value, bool):
        return False
    return "enum" not in schema or value in schema["enum"]


def _json_text_validator(schema: Optional[Dict[str, Any]] = None):
    def validate(text: str) -> bool:
        try:
            return _schema_accepts(json.loads(text), schema)
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
    return validate


def generate_json(
    prompt: str,
    *,
    system: str = "",
    model: str = "",
    cache_key: Optional[str] = None,
    ttl_s: int = CACHE_TTL_SECONDS,
    provider: str = "gemini",
    task_type: str = "generation",
    prompt_version: str = "",
    cache_context: str = "",
    max_tokens: Optional[int] = None,
) -> LLMResponse:
    """Generate text and parse as JSON. Raises on invalid JSON."""
    import re as _re

    resp = generate_text(
        prompt, system=system, model=model,
        json_mode=True, cache_key=cache_key, ttl_s=ttl_s,
        provider=provider,
        task_type=task_type,
        prompt_version=prompt_version,
        cache_context=cache_context,
        max_tokens=max_tokens,
        cache_validator=_json_text_validator(),
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


def generate_multimodal_text(
    prompt: str, image_bytes: bytes, *, mime_type: str = "image/png",
    max_tokens: int = 8192, task_type: str = "ocr",
) -> LLMResponse:
    """Metered Gemini multimodal generation used by selective OCR."""
    enforce_budget(); _enforce_user_quota()
    from google import genai
    from google.genai import types

    model = _model_for_task(task_type)
    if model not in LLM_PRICING:
        raise ValueError(f"No pricing configured for model: {model}")
    started = time.time()
    client = genai.Client(api_key=_google_api_key())
    response = client.models.generate_content(
        model=model,
        contents=[prompt, types.Part.from_bytes(data=image_bytes, mime_type=mime_type)],
        config=types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            thinking_config=(
                types.ThinkingConfig(thinking_budget=0)
                if model.removeprefix("models/").startswith("gemini-2.5-")
                else types.ThinkingConfig(thinking_level="minimal")
            ),
        ),
    )
    meta = getattr(response, "usage_metadata", None)
    prompt_tokens = int(getattr(meta, "prompt_token_count", 0) or estimate_tokens(prompt))
    candidates = int(getattr(meta, "candidates_token_count", 0) or estimate_tokens(response.text or ""))
    thoughts = int(getattr(meta, "thoughts_token_count", 0) or 0)
    cached = int(getattr(meta, "cached_content_token_count", 0) or 0)
    completion_tokens = candidates + thoughts
    cost_nanos = estimate_cost_nanos(model, prompt_tokens, completion_tokens, cached)
    usage = LLMUsage(
        prompt_tokens=prompt_tokens, completion_tokens=candidates,
        total_tokens=prompt_tokens + candidates + thoughts,
        cost_estimate=cost_nanos / 1_000_000_000,
        model=model, latency_ms=round((time.time() - started) * 1000, 1),
        cache_hit=False, provider="gemini", reasoning_tokens=thoughts,
        cached_tokens=cached,
        task_type=task_type,
        finish_reason=str(getattr(
            (getattr(response, "candidates", None) or [None])[0], "finish_reason", "STOP"
        )),
    )
    record_usage(prompt_tokens, completion_tokens, usage.cost_estimate)
    _attribute_to_current_user(
        prompt_tokens, completion_tokens, provider="gemini", model=model,
        reasoning_tokens=thoughts, cached_tokens=cached, cost_nanos=cost_nanos,
        usage_source="provider" if meta else "estimated", task_type=task_type,
    )
    _record_run_usage(usage)
    return LLMResponse(text=(response.text or "").strip(), usage=usage, raw=response)


def generate_response_json(
    prompt: str,
    *,
    system: str,
    schema: Dict[str, Any],
    schema_name: str,
    model: str = "",
    reasoning_effort: str = "high",
    pro_mode: bool = False,
    cache_key: Optional[str] = None,
    ttl_s: int = CACHE_TTL_SECONDS,
    task_type: str = "report_structured",
    thinking_level: str = "",
    max_tokens: Optional[int] = None,
    prompt_version: str = "",
    cache_context: str = "",
    validation_model=None,
    semantic_validator=None,
) -> LLMResponse:
    """Generate quality-critical structured reports with Gemini JSON schema.

    The legacy OpenAI Responses path made report completion depend on a second
    provider and bypassed the Gemini-only report policy.  Keep the older
    arguments for call-site compatibility, but all structured reports now use
    the same metered Gemini 3.6 Flash path and medium thinking.
    """
    response = generate_text(
        prompt,
        system=system,
        model="gemini-3.6-flash",
        provider="gemini",
        json_mode=True,
        response_schema=schema,
        thinking_level=thinking_level or get_task_profile(task_type).thinking_level,
        task_type=task_type,
        cache_key=cache_key,
        ttl_s=ttl_s,
        max_tokens=max_tokens or get_task_profile(task_type).max_output_tokens,
        prompt_version=prompt_version,
        cache_context=cache_context,
        cache_validator=lambda text: _structured_text_validator(
            text, schema, validation_model, semantic_validator,
        ),
    )
    response.raw = json.loads(response.text)
    if validation_model is not None:
        response.raw = validation_model.model_validate(response.raw).model_dump()
    if semantic_validator is not None and not semantic_validator(response.raw):
        raise LLMInvalidStructuredOutputError("model_output_invalid")
    return response


def _validate_with_model(text: str, validation_model) -> bool:
    try:
        validation_model.model_validate(json.loads(text))
        return True
    except Exception:
        return False


def _structured_text_validator(
    text: str, schema: Dict[str, Any], validation_model=None, semantic_validator=None,
) -> bool:
    try:
        value = json.loads(text)
        if validation_model is not None:
            validation_model.model_validate(value)
        elif not _schema_accepts(value, schema):
            return False
        return semantic_validator(value) if semantic_validator is not None else True
    except Exception:
        return False


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
    providers = effective_providers(providers or LLM_PROVIDERS)
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
    with ThreadPoolExecutor(max_workers=len(providers)) as executor:
        futures = [executor.submit(_ctxvars.copy_context().run, _call_provider, p)
                   for p in providers]
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
