"""Versioned prompt contract for the construction chronology pipeline."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Dict

from .config import BASE_DIR


PROMPT_FILE = Path(BASE_DIR) / "config" / "prompts" / "chronology_v2.yaml"


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


__all__ = ["chronology_prompt_hash", "load_chronology_prompts"]
