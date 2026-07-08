"""Narrative Guard — keeps LLM prose inside the deterministic ToolResult.

Two layers:
  1. deterministic rules (no LLM): invented dates/metrics, forbidden
     causation/entitlement lexicon, as-recorded→as-built substitution,
     dropped caveats, partial-presented-as-complete;
  2. one lite-model JSON groundedness check.

Verdict only — rewriting is the composer's job (max 1 attempt there).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import List

from ..schemas import STATUS_COMPLETE, ToolResult

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2} (Jan|Feb|Mar|Apr|May|Jun|"
                      r"Jul|Aug|Sep|Oct|Nov|Dec)\w* \d{4}\b", re.IGNORECASE)
_PARTIES = r"(contractor|employer|engineer|client|subcontractor|owner|consultant)"
_FORBIDDEN = [
    (re.compile(r"\bentitle\w*", re.I), "entitlement conclusion"),
    (re.compile(r"\bculpab\w*|\bliab\w*|\bat fault\b|\bblame\w*", re.I),
     "liability/blame attribution"),
    # Passive ("caused by the contractor") AND active ("the contractor caused")
    (re.compile(rf"caused by the {_PARTIES}", re.I),
     "responsibility attribution"),
    (re.compile(rf"\bthe {_PARTIES}('s)?\s+(caused|delayed|is responsible|"
                r"was responsible|failed to)", re.I),
     "responsibility attribution"),
    # Screening output must never be sold as proof of anything.
    (re.compile(r"\bforensic proof\b|\bprove[sdn]?\b|\bconclusively\b", re.I),
     "screening presented as proof"),
]

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


@dataclass
class GuardVerdict:
    approved: bool
    violations: List[str] = field(default_factory=list)


def _normalize_date(text: str) -> str:
    """'12 March 2026' / '2026-03-12' → '2026-03-12' for containment checks."""
    m = re.match(r"(\d{1,2}) (\w{3})\w* (\d{4})", text, re.IGNORECASE)
    if m:
        day, mon, year = int(m.group(1)), _MONTHS.get(m.group(2).lower(), 0), m.group(3)
        return f"{year}-{mon:02d}-{day:02d}"
    return text


def check_rules(narrative: str, result: ToolResult) -> List[str]:
    """Layer 1 — deterministic; returns violation strings."""
    violations: List[str] = []
    corpus = result.to_json()

    # Invented dates: every date in the narrative must exist in the ToolResult.
    for m in _DATE_RE.finditer(narrative):
        iso = _normalize_date(m.group(0))
        if iso[:10] not in corpus:
            violations.append(f"date '{m.group(0)}' does not appear in the computed output")

    # Forbidden lexicon.
    for rx, label in _FORBIDDEN:
        hit = rx.search(narrative)
        if hit:
            violations.append(f"{label}: '{hit.group(0)}'")

    # as-recorded must never become as-built.
    if "as-recorded" in corpus and "as-built" not in corpus.lower():
        if re.search(r"as[- ]built", narrative, re.IGNORECASE):
            violations.append("'as-recorded' output described as 'as-built'")

    # Every caveat must be represented (loose token-overlap match).
    low = narrative.lower()
    for caveat in result.caveats:
        tokens = [t for t in re.findall(r"[a-z]{4,}", caveat.lower())][:12]
        if not tokens:
            continue
        present = sum(1 for t in tokens if t in low)
        if present / len(tokens) < 0.6:
            violations.append(f"caveat not carried into the narrative: '{caveat[:80]}'")

    # Unconfirmed fuzzy matches must never be narrated as confirmed.
    raw_json = json.dumps(result.raw or {}, default=str)
    if ('"needs_confirmation"' in raw_json
            and '"needs_confirmation": []' not in raw_json):
        for m in re.finditer(r"\bconfirmed\b", low):
            ctx = low[max(0, m.start() - 20):m.start()]
            if "not " in ctx or "un" == low[max(0, m.start() - 2):m.start()]:
                continue
            violations.append(
                "unconfirmed milestone match described as confirmed")
            break

    # Partial/failed results must be labeled as such.
    if result.status != STATUS_COMPLETE:
        if not re.search(r"partial|incomplete|could not|failed", low):
            violations.append(f"'{result.status}' analysis presented without a "
                              "partial/incomplete statement")

    return violations


def check_grounding_llm(narrative: str, result: ToolResult) -> List[str]:
    """Layer 2 — one lite-model JSON check. Fails OPEN (LLM outage must not
    block a deterministic result; layer 1 already caught the hard failures)."""
    try:
        from src import llm_client
        from src.config import GEMINI_MODEL_LITE
        from src.prompt_security import build_system_prompt

        prompt = (
            "You are checking an AI-generated narrative against deterministic "
            "programme-analysis output.\n\nRules: the narrative must describe "
            "only the supplied output; it must not introduce new dates, delays, "
            "causes, liabilities, entitlement, responsibility or legal "
            "conclusions; it must not convert 'as-recorded' into 'as-built'; "
            "it must include the caveats; a partial/failed analysis must not "
            "be presented as complete.\n\n"
            f"ANALYSIS OUTPUT (ground truth):\n{result.to_json()[:6000]}\n\n"
            f"NARRATIVE:\n{narrative[:6000]}\n\n"
            'Return JSON only: {"grounded": true|false, "violations": ["..."]}'
        )
        resp = llm_client.generate_json(
            prompt,
            system=build_system_prompt(
                "You verify narrative groundedness. JSON only."),
            model=GEMINI_MODEL_LITE,
        )
        data = resp.raw if isinstance(resp.raw, dict) else {}
        if data.get("grounded") is False:
            return [str(v) for v in (data.get("violations") or ["ungrounded narrative"])][:5]
    except Exception as e:
        logger.debug(f"[NarrativeGuard] LLM check skipped (fail-open): {e}")
    return []


def check_narrative(narrative: str, result: ToolResult) -> GuardVerdict:
    if not (narrative or "").strip():
        return GuardVerdict(False, ["empty narrative"])
    violations = check_rules(narrative, result)
    if not violations:
        violations = check_grounding_llm(narrative, result)
    return GuardVerdict(approved=not violations, violations=violations)
