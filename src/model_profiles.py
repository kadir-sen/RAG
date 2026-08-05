"""Provider capabilities and task-specific LLM budgets.

Hard model limits describe what the provider accepts.  Task profiles describe
what COAir deliberately permits.  Keeping those concepts separate prevents a
small classifier from inheriting a 64K response while allowing evidence-heavy
reports to use the model they are actually paying for.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ModelCapabilities:
    input_tokens: int
    output_tokens: int
    thinking_levels: tuple[str, ...]
    structured_output: bool = True


@dataclass(frozen=True)
class TaskProfile:
    name: str
    max_input_tokens: int
    max_output_tokens: int
    thinking_level: str
    timeout_seconds: int
    provider_retries: int = 3


MODEL_CAPABILITIES: Dict[str, ModelCapabilities] = {
    "gemini-3.6-flash": ModelCapabilities(
        input_tokens=1_048_576,
        output_tokens=65_536,
        thinking_levels=("minimal", "low", "medium", "high"),
    ),
    # Retained for legacy non-demo routes.  Chronology never selects it.
    "gemini-3.5-flash-lite": ModelCapabilities(
        input_tokens=1_048_576,
        output_tokens=65_536,
        thinking_levels=("minimal", "low", "medium", "high"),
    ),
    "gemini-2.5-flash": ModelCapabilities(
        input_tokens=1_048_576,
        output_tokens=65_536,
        thinking_levels=("off", "low", "medium", "high"),
    ),
    "gemini-2.5-flash-lite": ModelCapabilities(
        input_tokens=1_048_576,
        output_tokens=65_536,
        thinking_levels=("off", "low", "medium", "high"),
    ),
}


TASK_PROFILES: Dict[str, TaskProfile] = {
    "routing_classification": TaskProfile(
        "routing_classification", 16_384, 1_024, "minimal", 45,
    ),
    "chat_answer": TaskProfile("chat_answer", 131_072, 8_192, "medium", 120),
    "research_plan": TaskProfile("research_plan", 32_768, 4_096, "low", 90),
    "chronology_research_plan": TaskProfile(
        "chronology_research_plan", 32_768, 4_096, "low", 90,
    ),
    "query_expansion": TaskProfile("query_expansion", 32_768, 4_096, "low", 90),
    "rerank": TaskProfile("rerank", 65_536, 4_096, "low", 90),
    "chronology_extract": TaskProfile(
        "chronology_extract", 196_608, 16_384, "low", 180,
    ),
    "chronology_aggregation": TaskProfile(
        "chronology_aggregation", 196_608, 16_384, "low", 180,
    ),
    "chronology_synthesis": TaskProfile(
        "chronology_synthesis", 262_144, 32_768, "medium", 240,
    ),
    "chronology_verify": TaskProfile(
        "chronology_verify", 65_536, 8_192, "low", 120,
    ),
    "report_structured": TaskProfile(
        "report_structured", 262_144, 32_768, "medium", 240,
    ),
    "ocr": TaskProfile("ocr", 65_536, 16_384, "minimal", 180),
    "metadata": TaskProfile("metadata", 65_536, 4_096, "minimal", 120),
    "sql": TaskProfile("sql", 65_536, 4_096, "medium", 90),
    "generation": TaskProfile("generation", 131_072, 8_192, "medium", 120),
}


def get_task_profile(task_type: str) -> TaskProfile:
    key = (task_type or "generation").strip().lower()
    key = {
        "classification": "routing_classification",
        "scope": "routing_classification",
        "answer_check": "routing_classification",
        "ingestion_metadata": "metadata",
        "ingestion_notice_metadata": "metadata",
        "ingestion_cluster_label": "metadata",
        "ingestion_classification": "metadata",
        "query_plan": "research_plan",
        "answer_synthesis": "chat_answer",
        "document_synthesis": "chat_answer",
    }.get(key, key)
    return TASK_PROFILES.get(key, TASK_PROFILES["generation"])


def clamp_output_tokens(model: str, requested: int, profile: TaskProfile) -> int:
    capability = MODEL_CAPABILITIES.get(model)
    hard_limit = capability.output_tokens if capability else profile.max_output_tokens
    return max(1, min(int(requested or profile.max_output_tokens),
                      profile.max_output_tokens, hard_limit))


def validate_profile(model: str, profile: TaskProfile) -> None:
    capability = MODEL_CAPABILITIES.get(model)
    if capability is None:
        return
    if profile.max_input_tokens > capability.input_tokens:
        raise ValueError(f"{profile.name} input budget exceeds {model} capability")
    if profile.max_output_tokens > capability.output_tokens:
        raise ValueError(f"{profile.name} output budget exceeds {model} capability")
    if profile.thinking_level not in capability.thinking_levels:
        raise ValueError(f"{profile.name} uses unsupported thinking level")


for _profile in TASK_PROFILES.values():
    validate_profile("gemini-3.6-flash", _profile)


__all__ = [
    "MODEL_CAPABILITIES", "TASK_PROFILES", "ModelCapabilities", "TaskProfile",
    "clamp_output_tokens", "get_task_profile", "validate_profile",
]
