"""Delay-report tool registry.

Same contract layer as programme_tools: the router may only route to tool_ids
registered here; a query matches iff ≥1 positive trigger AND 0 negative
triggers. Sprint 1 ships one tool (user-defined event chronology); Sprint 2
adds delay_events.suggest_candidates as pure data here.
"""

from __future__ import annotations

import re
from typing import Dict, Optional

# Reuse the proven spec dataclass — no second trigger framework.
from ..programme_tools.registry import ToolInput, ToolSpec

# Queries these words indicate belong elsewhere: programme metrics → programme
# tools; causation/liability/entitlement → Trust-Guarded document path;
# letter drafting → correspondence path.
SHARED_NEGATIVE_TRIGGERS = [
    r"\bdcma\b", r"milestone", r"programme health", r"schedule health",
    r"\bmanpower\b", r"histogram", r"equipment",
    r"who (is |was )?(caused|responsible)", r"who caused",
    r"\bentitle", r"\bliab", r"culpab", r"eot claim assessment",
    r"draft a (reply|letter|response)",
    r"summari[sz]e (all|generally|the project)",
]

REGISTRY: Dict[str, ToolSpec] = {
    "delay_reports.event_chronology": ToolSpec(
        tool_id="delay_reports.event_chronology",
        title="Delay Event Chronology Section",
        description="Forensic, claim-report-style chronology: numbered, "
                    "date-sorted, actor-attributed narrative paragraphs with "
                    "per-paragraph source references, built from correspondence "
                    "evidence for a user-named delay event.",
        inputs=[ToolInput(
            name="event_title", type="string", required=True,
            description="The delay event to build the chronology for "
                        "(e.g. 'Delayed Blockwork')",
            missing_message="Please name the delay event, e.g. "
                            "\"Prepare detailed chronology for Delayed Blockwork\".",
        )],
        output_schema="numbered narrative section + chronology table + "
                      "evidence list + caveats",
        positive_triggers=[
            r"(prepare|create|build|write|produce|generate|draft)\b.*chronolog",
            r"chronolog\w*\s+(for|of|in|section)\b",   # "chronology in 6.1 format"
            r"6\.1\s*(style|format|section)",           # style OR format OR section
            r"'s\s+chronolog",                          # "Blockwork's chronology"
            r"(claim|forensic)\s+chronolog",            # "claim/forensic chronology"
            r"delay\s+(event\s+)?(narrative|report\s+section|section)",
            r"(narrative|report)\s+section\s+.*\bdelay",
            r"(identify|find|extract)\b.*delay events?",
        ],
        negative_triggers=SHARED_NEGATIVE_TRIGGERS,
        min_xer_files=0,
    ),
}


def match_query(query: str) -> Optional[Dict[str, str]]:
    """Deterministic intent match. {'kind':'tool','id':...} or None."""
    q = (query or "").lower()
    for spec in REGISTRY.values():
        if spec.matches(q):
            return {"kind": "tool", "id": spec.tool_id}
    return None
