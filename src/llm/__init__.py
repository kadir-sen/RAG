"""COAir LLM gateway — one task-based entrypoint for every LLM call.

    from src.llm import gateway
    result = gateway.complete("rag_answer_synthesis", prompt, system=...)
    if result.status == "degraded":
        show(result.degraded_message)   # user-safe; never a raw provider error

Model choice is by task (policy.py) → logical group (registry.py). Fallback,
timeout, error sanitization and usage logging are centralized here so no raw
429/quota/billing text ever reaches the user.
"""

from . import gateway
from .errors import LLMErrorType, classify_error, sanitize
from .gateway import GatewayResult, complete
from .policy import TASK_POLICY, select

__all__ = ["gateway", "complete", "GatewayResult", "select", "TASK_POLICY",
           "LLMErrorType", "classify_error", "sanitize"]
