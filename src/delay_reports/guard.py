"""Chronology narrative guard.

Layer 1: the programme narrative_guard's base rules (blame/entitlement
lexicon, proof words, caveat carry) PLUS chronology-specific deterministic
rules — dates ∈ register, chronological order, per-paragraph source refs,
actor whitelist, scope drift, paragraph count. Layer 2: one lite-LLM
groundedness check. Verdict only; the handler owns rewrite/fallback.
"""

from __future__ import annotations

import logging
import re
from typing import List

from ..programme_tools.guards.narrative_guard import (
    GuardVerdict, _FORBIDDEN, check_grounding_llm,
)
from .chronology import ChronologyTable
from .register import dates_in_text
from .schemas import ScopeResult, ToolResult

logger = logging.getLogger(__name__)

_PARA_RE = re.compile(r"^(\d+\.\d+\.\d+)\b", re.MULTILINE)
# Filenames may themselves contain parentheses ("items (55).msg") — allow one
# nesting level inside the source ref.
_SOURCE_REF_RE = re.compile(r"\(((?:[^()]|\([^()]*\))+?),\s*p\.?\s*\d+\)")


def chronology_rules(narrative: str, table: ChronologyTable,
                     scope: ScopeResult) -> List[str]:
    """Deterministic chronology rules. Returns violation strings."""
    violations: List[str] = []
    if not (narrative or "").strip():
        return ["empty narrative"]

    expected_paras = [r.para_no for r in table.rows]
    found_paras = _PARA_RE.findall(narrative)

    # 1. Every expected paragraph present exactly once, consecutive order.
    if found_paras != expected_paras:
        missing = [p for p in expected_paras if p not in found_paras]
        extra = [p for p in found_paras if p not in expected_paras]
        if missing:
            violations.append(f"missing paragraph(s): {', '.join(missing[:5])}")
        if extra:
            violations.append(f"unexpected paragraph number(s): {', '.join(extra[:5])}")
        if not missing and not extra:
            violations.append("paragraphs are out of order")

    register_dates = {r.date for r in table.rows}
    register_files = {r.entry.file_name for r in table.rows}
    # Known-names corpus for the party check: actors/recipients/parties PLUS
    # the register's issue/quote text — subject-line phrases ("Vingcard
    # Corridor Panel RFI") legitimately appear in narrative paragraphs and
    # must not be flagged as unknown parties.
    register_actors = " ".join(
        [r.entry.actor for r in table.rows]
        + [r.entry.recipient or "" for r in table.rows]
        + [r.entry.issue for r in table.rows]
        + [r.entry.quote for r in table.rows]
        + [r.entry.file_name for r in table.rows]
        + (scope.parties or [])
        + ([scope.event_title] if scope.event_title else [])
    ).lower()

    # Split narrative into per-paragraph chunks for rules 2-4.
    chunks = re.split(r"(?=^\d+\.\d+\.\d+\b)", narrative, flags=re.MULTILINE)
    para_chunks = [c for c in chunks if _PARA_RE.match(c.strip())]

    for chunk in para_chunks:
        para_no = _PARA_RE.match(chunk.strip()).group(1)
        # Paragraph numbers ("6.1.13") would false-match the numeric
        # day-first date pattern — strip them before the date scan.
        chunk_dates_text = re.sub(r"\b\d+\.\d+\.\d+\b", " ", chunk)
        # 2. Every date in the paragraph must exist in the register.
        for iso in dates_in_text(chunk_dates_text):
            if iso not in register_dates:
                violations.append(
                    f"{para_no}: date {iso} does not appear in the validated register")
        # 3. Every paragraph must carry a (file, p.N) ref to a register file.
        refs = _SOURCE_REF_RE.findall(chunk)
        if not refs:
            violations.append(f"{para_no}: no source reference")
        elif not any(ref.strip() in register_files for ref in refs):
            violations.append(
                f"{para_no}: source reference does not match any evidence file")
        # 4. Capitalized multi-word names must be known actors/parties.
        for m in re.finditer(r"\b([A-Z][A-Za-z]+(?:[ -][A-Z][A-Za-z]+)+)\b", chunk):
            name = m.group(1)
            if name.split()[0].lower() in ("on", "it", "the"):
                continue
            if name.lower() not in register_actors and \
                    not all(t.lower() in register_actors for t in name.split()):
                violations.append(f"{para_no}: unknown party '{name}'")
                break  # one per paragraph is enough signal

    # 5. Forbidden legal-conclusion lexicon (reuse programme list).
    for rx, label in _FORBIDDEN:
        hit = rx.search(narrative)
        if hit:
            violations.append(f"{label}: '{hit.group(0)}'")

    # 6. Scope drift: the event title must anchor the narrative.
    if scope.event_title:
        title_tokens = [t for t in re.findall(r"[a-z]{4,}", scope.event_title.lower())]
        low = narrative.lower()
        if title_tokens and not any(t in low for t in title_tokens):
            violations.append("narrative does not mention the requested event")

    return violations


def chronology_guard(narrative: str, table: ChronologyTable,
                     scope: ScopeResult, result: ToolResult) -> GuardVerdict:
    violations = chronology_rules(narrative, table, scope)
    if not violations:
        violations = check_grounding_llm(narrative, result)
    return GuardVerdict(approved=not violations, violations=violations)
