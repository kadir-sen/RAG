"""Logical model registry — the ONLY place concrete provider model names live.

Callers reference logical model groups ("standard_synthesis"); the gateway
resolves groups → ordered ModelSpecs. Adding DeepSeek/Claude/gemini-pro later
is a data edit here (flip `enabled`), not a code change across the app.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class ModelSpec:
    model_id: str              # logical id, e.g. "gemini_flash"
    provider: str              # "gemini" | "openai" | "claude" | "deepseek"
    provider_model_name: str   # concrete string — lives ONLY here
    supports_json: bool
    max_output_tokens: int
    input_cost: float          # $/1M (from config.LLM_PRICING)
    output_cost: float         # $/1M
    default_timeout_s: int
    enabled: bool


def _cost(provider_model_name: str) -> tuple[float, float]:
    from src.config import LLM_PRICING
    p = LLM_PRICING.get(provider_model_name, {})
    return float(p.get("input", 0.0)), float(p.get("output", 0.0))


def _spec(model_id, provider, provider_model_name, *, supports_json=True,
          max_output_tokens=2048, timeout=30, enabled=True) -> ModelSpec:
    ci, co = _cost(provider_model_name)
    return ModelSpec(model_id, provider, provider_model_name, supports_json,
                     max_output_tokens, ci, co, timeout, enabled)


# gemini_pro / deepseek / claude are registered but OFF — plug-in seam for the
# next sprint (per-$ budgets, cross-provider fallback). Enable via env or here.
_GEMINI_PRO_ENABLED = os.getenv("ENABLE_GEMINI_PRO", "false").lower() in ("1", "true", "yes")

MODEL_REGISTRY: Dict[str, ModelSpec] = {
    "gemini_flash": _spec("gemini_flash", "gemini", "gemini-2.5-flash"),
    "gemini_flash_lite": _spec("gemini_flash_lite", "gemini", "gemini-2.5-flash-lite"),
    "gemini_pro": _spec("gemini_pro", "gemini", "gemini-1.5-pro",
                        max_output_tokens=4096, timeout=45,
                        enabled=_GEMINI_PRO_ENABLED),
    "deepseek_chat": _spec("deepseek_chat", "deepseek", "deepseek-chat",
                           enabled=False),
    "claude_sonnet": _spec("claude_sonnet", "claude", "claude-sonnet-4-20250514",
                           enabled=False),
}

# Logical groups → ordered concrete model_ids (primary first).
MODEL_GROUPS: Dict[str, List[str]] = {
    "cheap_json": ["gemini_flash_lite"],
    "cheap_classifier": ["gemini_flash_lite"],
    "standard_synthesis": ["gemini_flash", "gemini_flash_lite"],
    "standard_reasoning": ["gemini_flash"],
    "premium_review": ["gemini_pro", "gemini_flash"],
}


def resolve_group(group: str) -> List[ModelSpec]:
    """Ordered ENABLED ModelSpecs for a logical group (disabled filtered out)."""
    out: List[ModelSpec] = []
    for mid in MODEL_GROUPS.get(group, []):
        spec = MODEL_REGISTRY.get(mid)
        if spec and spec.enabled:
            out.append(spec)
    return out
