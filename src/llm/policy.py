"""Task-to-model policy — one row per LLM task type in COAir.

Encodes the owner's non-negotiables directly: guards fail-open with an
"unverified" surface (never blocked, never downgraded to a cheaper reasoning
tier for cost); final review fails closed; deterministic-fallback tasks keep
their zero-LLM path. Model choice is by task, never a hardcoded model string.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .registry import ModelSpec, resolve_group


@dataclass(frozen=True)
class TaskPolicy:
    task_type: str
    model_group: str
    fallback_group: str
    json_mode: bool = False
    fail_open: bool = True
    deterministic_fallback: bool = False
    max_output_tokens: int = 2048
    timeout_s: int = 30
    retries: int = 1
    fallback_message: str = ""


# 15 task types. fallback_message is what the USER sees on total failure —
# never a raw provider error.
_SQL_MSG = ("SQL analysis is temporarily unavailable; please narrow the "
           "question or try again shortly.")
_VERIFY_MSG = ("Verification is temporarily unavailable; this answer is marked "
              "unverified — analyst review is recommended.")

TASK_POLICY = {
    "classify_query": TaskPolicy(
        "classify_query", "cheap_classifier", "cheap_classifier",
        json_mode=True, fail_open=True, deterministic_fallback=True,
        max_output_tokens=64, timeout_s=15),
    "route_tool": TaskPolicy(
        "route_tool", "cheap_classifier", "cheap_classifier",
        json_mode=True, fail_open=True, deterministic_fallback=True,
        max_output_tokens=64, timeout_s=15),
    "rag_answer_synthesis": TaskPolicy(
        "rag_answer_synthesis", "standard_synthesis", "standard_synthesis",
        fail_open=False, max_output_tokens=1500, timeout_s=40,
        fallback_message="The assistant is temporarily unable to compose an "
                         "answer. Please retry shortly."),
    "rag_evidence_summary": TaskPolicy(
        "rag_evidence_summary", "cheap_json", "cheap_json",
        fail_open=True, max_output_tokens=800,
        fallback_message="Summary is temporarily unavailable."),
    "sql_generation": TaskPolicy(
        "sql_generation", "standard_reasoning", "standard_synthesis",
        fail_open=False, deterministic_fallback=True, max_output_tokens=512,
        timeout_s=35, fallback_message=_SQL_MSG),
    "sql_result_summary": TaskPolicy(
        "sql_result_summary", "cheap_json", "cheap_json",
        fail_open=True, deterministic_fallback=True, max_output_tokens=512,
        fallback_message="Showing the computed results; the narrative summary "
                         "is temporarily unavailable."),
    "trust_guard_verification": TaskPolicy(
        "trust_guard_verification", "standard_reasoning", "standard_reasoning",
        json_mode=True, fail_open=True, max_output_tokens=1500,
        fallback_message=_VERIFY_MSG),
    "narrative_guard_grounding": TaskPolicy(
        "narrative_guard_grounding", "cheap_json", "cheap_json",
        json_mode=True, fail_open=True, max_output_tokens=800,
        fallback_message=""),
    "programme_narrative_draft": TaskPolicy(
        "programme_narrative_draft", "standard_synthesis", "standard_synthesis",
        fail_open=False, deterministic_fallback=True, max_output_tokens=1500,
        fallback_message="Narrative drafting is temporarily unavailable; "
                         "the computed results are shown."),
    "delay_chronology_narrative": TaskPolicy(
        "delay_chronology_narrative", "standard_synthesis", "standard_synthesis",
        fail_open=False, deterministic_fallback=True, max_output_tokens=2000,
        fallback_message="Chronology narrative is temporarily unavailable; "
                         "the structured timeline is shown."),
    "html_report_section_draft": TaskPolicy(
        "html_report_section_draft", "standard_synthesis", "standard_synthesis",
        fail_open=False, deterministic_fallback=True,
        fallback_message="Report formatting is temporarily unavailable; "
                         "the plain results are shown."),
    "chart_explanation": TaskPolicy(
        "chart_explanation", "cheap_json", "cheap_json",
        fail_open=True, max_output_tokens=500,
        fallback_message="Chart explanation is temporarily unavailable."),
    "react_agent_reasoning": TaskPolicy(
        "react_agent_reasoning", "standard_reasoning", "standard_synthesis",
        json_mode=True, fail_open=True, deterministic_fallback=True,
        max_output_tokens=1024, timeout_s=40, fallback_message=""),
    "final_claim_section_review": TaskPolicy(
        "final_claim_section_review", "premium_review", "standard_reasoning",
        json_mode=True, fail_open=False, max_output_tokens=1500, timeout_s=45,
        fallback_message="This section requires reviewer verification, which "
                         "is temporarily unavailable — flagged for analyst "
                         "review."),
    "degraded_mode_message": TaskPolicy(
        "degraded_mode_message", "cheap_classifier", "cheap_classifier",
        fail_open=True, deterministic_fallback=True, max_output_tokens=128,
        fallback_message=""),
}

DEFAULT_TASK = "rag_answer_synthesis"


@dataclass
class ResolvedChain:
    policy: TaskPolicy
    models: List[ModelSpec] = field(default_factory=list)


def select(task_type: str) -> ResolvedChain:
    """Ordered ModelSpec chain (primary group then fallback group, deduped,
    disabled filtered). The deterministic sentinel is not a ModelSpec — the
    gateway consults policy.deterministic_fallback after the chain is spent."""
    policy = TASK_POLICY.get(task_type) or TASK_POLICY[DEFAULT_TASK]
    seen = set()
    models: List[ModelSpec] = []
    for group in (policy.model_group, policy.fallback_group):
        for spec in resolve_group(group):
            if spec.model_id not in seen:
                seen.add(spec.model_id)
                models.append(spec)
    return ResolvedChain(policy=policy, models=models)
