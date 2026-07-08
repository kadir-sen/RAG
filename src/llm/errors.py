"""Error classification + sanitization — where the raw 429 leak dies.

Budget/quota exceptions are re-raised (must reach the FastAPI 402 handler).
Everything else is classified from the wrapped RuntimeError text (llm_client
emits `LLM call failed (gemini): <raw google 429 + billing url>`), then mapped
to a user-safe message that NEVER contains provider internals.
"""

from __future__ import annotations

import re
from enum import Enum


class LLMErrorType(str, Enum):
    RATE_LIMIT = "RATE_LIMIT"
    BILLING_QUOTA = "BILLING_QUOTA"
    AUTH = "AUTH"
    TIMEOUT = "TIMEOUT"
    PROVIDER_DOWN = "PROVIDER_DOWN"
    MALFORMED_JSON = "MALFORMED_JSON"
    CONTEXT_WINDOW = "CONTEXT_WINDOW"
    CONTENT_POLICY = "CONTENT_POLICY"
    UNKNOWN = "UNKNOWN"


# Transient types where advancing the fallback chain is worthwhile.
_ADVANCE = {
    LLMErrorType.RATE_LIMIT, LLMErrorType.BILLING_QUOTA,
    LLMErrorType.TIMEOUT, LLMErrorType.PROVIDER_DOWN,
    LLMErrorType.MALFORMED_JSON, LLMErrorType.CONTEXT_WINDOW,
    LLMErrorType.PROVIDER_DOWN,
}
# Same-model retry allowed (once) before advancing.
_SAME_MODEL_RETRY = {LLMErrorType.TIMEOUT, LLMErrorType.MALFORMED_JSON}


class BudgetError(Exception):
    """Re-raised marker so callers know budget/quota must bubble to 402."""


def classify_error(exc: Exception) -> LLMErrorType:
    """Classify an LLM exception. Budget/quota exceptions are RE-RAISED, not
    classified — they must reach the 402 handler untouched."""
    # 1. Budget/quota → re-raise (never sanitized, never retried).
    try:
        from src.usage_tracker import BudgetExceededError
    except Exception:
        BudgetExceededError = ()  # type: ignore
    try:
        from src.user_store import UserQuotaExceededError
    except Exception:
        UserQuotaExceededError = ()  # type: ignore
    if BudgetExceededError and isinstance(exc, BudgetExceededError):
        raise exc
    if UserQuotaExceededError and isinstance(exc, UserQuotaExceededError):
        raise exc

    # 2. Provider SDK types (isinstance where available).
    try:
        import anthropic
        if isinstance(exc, getattr(anthropic, "RateLimitError", ())):
            return LLMErrorType.RATE_LIMIT
        if isinstance(exc, (getattr(anthropic, "AuthenticationError", ()),)):
            return LLMErrorType.AUTH
    except Exception:
        pass
    try:
        import openai
        if isinstance(exc, getattr(openai, "RateLimitError", ())):
            return LLMErrorType.RATE_LIMIT
        if isinstance(exc, getattr(openai, "AuthenticationError", ())):
            return LLMErrorType.AUTH
    except Exception:
        pass

    # 3. Regex on the wrapped message — catches the Gemini/OpenAI 429s the
    #    current code misses (only anthropic.RateLimitError was recognized).
    msg = str(exc).lower()
    if re.search(r"\bbilling\b|permission_denied|\b403\b|"
                 r"generativelanguage\.googleapis\.com|free_tier|"
                 r"check your plan", msg):
        return LLMErrorType.BILLING_QUOTA
    if re.search(r"\b429\b|resource_exhausted|rate.?limit|"
                 r"quota|exceeded your current", msg):
        # quota-flavoured 429s: treat as rate limit (advance tier); the billing
        # branch above already caught the hard billing/permission cases.
        return LLMErrorType.RATE_LIMIT
    if re.search(r"timbeout|timed? ?out|deadline|timeout", msg):
        return LLMErrorType.TIMEOUT
    if re.search(r"\b500\b|\b503\b|unavailable|overloaded|internal error", msg):
        return LLMErrorType.PROVIDER_DOWN
    if re.search(r"context length|token limit|too long|maximum context", msg):
        return LLMErrorType.CONTEXT_WINDOW
    if re.search(r"safety|blocked|content policy|content_filter", msg):
        return LLMErrorType.CONTENT_POLICY
    if re.search(r"did not return valid json|json ?decode|expecting value", msg):
        return LLMErrorType.MALFORMED_JSON
    return LLMErrorType.UNKNOWN


def should_advance(error_type: LLMErrorType) -> bool:
    """Advance to the next model in the chain for this error type."""
    return error_type in _ADVANCE or error_type in (
        LLMErrorType.AUTH, LLMErrorType.CONTENT_POLICY, LLMErrorType.UNKNOWN)


def allows_same_model_retry(error_type: LLMErrorType) -> bool:
    """TIMEOUT / MALFORMED_JSON get one same-model retry before advancing;
    RATE_LIMIT / BILLING_QUOTA never retry the same model."""
    return error_type in _SAME_MODEL_RETRY


def sanitize(task_policy, error_type: LLMErrorType) -> str:
    """User-safe message. NEVER interpolates the exception text."""
    return task_policy.fallback_message or (
        "This step is temporarily unavailable; please try again shortly.")
