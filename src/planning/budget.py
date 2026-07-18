"""Thinking-budget tiers (Sprint C).

A complexity tier scales how much retrieval / rerank / decomposition a prompt
earns. This does not invent new token knobs — it maps a tier onto the existing
static THINKING_BUDGET_* config values as a multiplier, and bounds the plan
size. small = direct route; large = multi-record retrieval + rerank + synthesis.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Budget:
    tier: str                 # small | medium | large
    max_subtasks: int
    retrieval_multiplier: float
    allow_rerank: bool
    allow_cross_encoder: bool
    thinking_multiplier: float


_BUDGETS = {
    "small":  Budget("small", max_subtasks=1, retrieval_multiplier=1.0,
                     allow_rerank=False, allow_cross_encoder=False,
                     thinking_multiplier=0.0),
    "medium": Budget("medium", max_subtasks=3, retrieval_multiplier=1.0,
                     allow_rerank=True, allow_cross_encoder=False,
                     thinking_multiplier=1.0),
    "large":  Budget("large", max_subtasks=8, retrieval_multiplier=1.5,
                     allow_rerank=True, allow_cross_encoder=True,
                     thinking_multiplier=2.0),
}

# complexity → thinking_budget tier
_COMPLEXITY_TO_TIER = {"low": "small", "medium": "medium", "high": "large"}


def tier_for_complexity(complexity: str) -> str:
    return _COMPLEXITY_TO_TIER.get(complexity, "medium")


def budget_for(tier: str) -> Budget:
    return _BUDGETS.get(tier, _BUDGETS["medium"])
