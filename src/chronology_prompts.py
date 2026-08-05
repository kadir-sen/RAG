"""Versioned prompt contract for the construction chronology pipeline."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Dict

from .config import BASE_DIR


PROMPT_FILE = Path(BASE_DIR) / "config" / "prompts" / "chronology_v2.yaml"
V3_PROMPT_FILE = Path(BASE_DIR) / "config" / "prompts" / "chronology_v3.yaml"


@lru_cache(maxsize=1)
def load_chronology_prompts() -> Dict[str, str]:
    # JSON is a strict YAML subset.  Keeping the file in that subset avoids a
    # runtime YAML dependency in the API image while retaining the requested
    # human-editable .yaml contract.
    raw = json.loads(PROMPT_FILE.read_text(encoding="utf-8"))
    required = {
        "version", "system", "research_planner", "extractor",
        "synthesizer", "verifier", "style_profile",
    }
    missing = required - set(raw)
    if missing or any(not str(raw.get(key) or "").strip() for key in required):
        raise RuntimeError(f"Invalid chronology prompt file; missing={sorted(missing)}")
    return {key: str(value).strip() for key, value in raw.items()}


def chronology_prompt_hash() -> str:
    payload = json.dumps(load_chronology_prompts(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def load_chronology_v3_prompts() -> Dict[str, str]:
    try:
        data = json.loads(V3_PROMPT_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Unable to load chronology V3 prompts: {V3_PROMPT_FILE}") from exc
    required = {
        "version", "system", "research_planner", "map_extractor", "extractor",
        "synthesizer", "verifier", "repair", "style_profile",
    }
    missing = required - data.keys()
    if missing:
        raise RuntimeError(f"Invalid chronology V3 prompt file; missing={sorted(missing)}")
    return {str(key): str(value) for key, value in data.items()}


def chronology_v3_prompt_hash() -> str:
    payload = json.dumps(load_chronology_v3_prompts(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_chronology_runtime() -> None:
    """Fail closed when a deploy omitted a prompt, model profile or price."""
    load_chronology_prompts(); v3 = load_chronology_v3_prompts()
    if v3.get("version") != "chronology-v3":
        raise RuntimeError("chronology_prompt_version_invalid")
    from .config import LLM_PRICING
    from .model_profiles import MODEL_CAPABILITIES, TASK_PROFILES
    model = "gemini-3.6-flash"
    if model not in LLM_PRICING or model not in MODEL_CAPABILITIES:
        raise RuntimeError("chronology_model_contract_missing")
    expected_price = {"input": 1.50, "cached_input": .15, "output": 7.50}
    if any(float(LLM_PRICING[model].get(key, -1)) != value
           for key, value in expected_price.items()):
        raise RuntimeError("chronology_model_price_invalid")
    required = {
        "chronology_research_plan", "chronology_extract", "chronology_aggregation",
        "chronology_synthesis", "chronology_verify",
    }
    if not required <= TASK_PROFILES.keys():
        raise RuntimeError("chronology_task_profile_missing")
    # Importing and materialising the schemas detects packaging/import drift
    # before a job can consume credits and fail at the first provider call.
    from .chronology_v3 import (
        ChronologyModel, ExtractionModel, MapExtractionModel, VerificationModel,
    )
    for schema in (ChronologyModel, ExtractionModel, MapExtractionModel, VerificationModel):
        if not schema.model_json_schema().get("properties"):
            raise RuntimeError("chronology_schema_invalid")


__all__ = [
    "chronology_prompt_hash", "chronology_v3_prompt_hash",
    "load_chronology_prompts", "load_chronology_v3_prompts",
    "validate_chronology_runtime",
]
