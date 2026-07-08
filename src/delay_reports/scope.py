"""Event scope resolution — turn the user's sentence into an event title.

Deterministic regex first ("chronology for X", "for the X event"); falls back
to the router's cached lite-LLM scope extraction (compute_query_scope topic).
Unresolvable → clarification, never a guessed event.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from .schemas import ScopeResult

logger = logging.getLogger(__name__)

# "prepare detailed chronology for (the) Delayed Blockwork (event)"
_FOR_OF_RE = re.compile(
    r"chronolog\w*\s+(?:for|of|on)\s+(?:the\s+)?(.+?)(?:\s+event)?\s*[.?!]?\s*$",
    re.IGNORECASE,
)
# "(narrative|report) section for (the) delayed access (event)"
_SECTION_FOR_RE = re.compile(
    r"(?:narrative|report|section)\s+(?:section\s+)?for\s+(?:the\s+)?(.+?)(?:\s+event)?\s*[.?!]?\s*$",
    re.IGNORECASE,
)
# "for the Delayed Blockwork event, prepare ..."
_EVENT_COMMA_RE = re.compile(
    r"for\s+the\s+(.+?)\s+event\s*,", re.IGNORECASE,
)
# Noun-first / possessive: "the Delayed Blockwork chronology",
# "Delayed Blockwork's chronology", "Blockwork delay chronology".
_NOUN_FIRST_RE = re.compile(
    r"(?:the\s+)?(.+?)(?:'s|s')?\s+(?:delay\s+)?chronolog\w*",
    re.IGNORECASE,
)

# A captured title containing an imperative/formatting verb means the regex
# swallowed a trailing instruction — reject it.
_INSTRUCTION_VERB_RE = re.compile(
    r"\b(use|include|show|format|with|make|provide|add|number|write|prepare|"
    r"create|generate|give|list|display)\b", re.IGNORECASE,
)
# Leading words of trailing instruction sentences to drop before extraction.
_TRAILING_INSTRUCTION_STARTERS = {
    "use", "include", "show", "format", "with", "make", "provide", "add",
    "number", "write", "keep", "ensure", "give", "list",
}

# Titles that are really "find events for me" (Sprint 2 territory).
_GENERIC_TITLES = {
    "the project", "project", "delays", "delay", "the delays", "main delay events",
    "delay events", "the delay events", "events", "all events", "correspondence",
    "the correspondence",
}

_STOP_TOKENS = {"the", "a", "an", "of", "for", "to", "in", "on", "and", "event"}

_CLARIFICATION = (
    "Please name the delay event you want the chronology for — for example: "
    "\"Prepare detailed chronology for Delayed Blockwork\". "
    "(Automatic delay-event discovery is planned for a future release.)"
)


def _strip_trailing_instructions(q: str) -> str:
    """Drop trailing instruction sentences so 'chronology for X. Use numbered
    paragraphs...' resolves to 'X', not 'X. Use numbered paragraphs'."""
    parts = re.split(r"(?<=[.?!])\s+", q)
    kept = []
    for i, part in enumerate(parts):
        first = re.sub(r"[^a-z]", "", part.split()[0].lower()) if part.split() else ""
        if i > 0 and first in _TRAILING_INSTRUCTION_STARTERS:
            break  # this and everything after is instruction, not scope
        kept.append(part)
    return " ".join(kept).strip()


def _clean_title(raw: str) -> Optional[str]:
    title = " ".join((raw or "").split()).strip(" .,:;\"'")
    # Trim trailing style qualifiers ("... in 6.1 style")
    title = re.sub(r"\s+in\s+6\.1\s*style$", "", title, flags=re.IGNORECASE).strip()
    # Drop a trailing instruction clause the regex may have swallowed.
    title = re.split(r"[.?!]", title)[0].strip()
    if not title or title.lower() in _GENERIC_TITLES or len(title) < 4:
        return None
    # Reject over-long captures and captures carrying instruction verbs
    # (both signatures of a swallowed trailing instruction).
    if len(title) > 60 or len(title.split()) > 8:
        return None
    if _INSTRUCTION_VERB_RE.search(title):
        return None
    return title


def topic_terms(title: str) -> list[str]:
    return [t for t in re.findall(r"[a-zA-Z]{3,}", title.lower())
            if t not in _STOP_TOKENS]


def resolve_event_scope(query: str, router: Any = None) -> ScopeResult:
    """Extract the user-defined event title. Never raises."""
    raw = " ".join((query or "").split())
    q = _strip_trailing_instructions(raw)

    # for/of/on and comma patterns first (most specific); noun-first last so it
    # only fires when the topic precedes the word "chronology".
    for rx in (_EVENT_COMMA_RE, _FOR_OF_RE, _SECTION_FOR_RE, _NOUN_FIRST_RE):
        m = rx.search(q)
        if m:
            title = _clean_title(m.group(1))
            if title:
                return ScopeResult(event_title=title,
                                   topic_terms=topic_terms(title))

    # Fallback: the router's cached lite-LLM scope (topic + actor + dates).
    if router is not None:
        try:
            scope = router.compute_query_scope(q) or {}
            title = _clean_title(scope.get("topic") or "")
            if title:
                return ScopeResult(
                    event_title=title,
                    topic_terms=topic_terms(title),
                    parties=[p for p in [scope.get("actor")] if p],
                    date_from=scope.get("date_from"),
                    date_to=scope.get("date_to"),
                )
        except Exception as e:
            logger.debug(f"[DelayReports] scope fallback failed: {e}")

    return ScopeResult(needs_clarification=True, clarification=_CLARIFICATION)
