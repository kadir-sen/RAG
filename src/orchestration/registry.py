"""Composite-intent catalog + capability whitelist.

The planner may only select intents registered here; runners are looked up
from an explicit whitelist (no LLM-named functions, ever). Triggers require
explicit multi-output wording ("as a chart", "html section", "and explain")
so plain single-skill queries keep their existing fast paths.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .schemas import CapabilitySpec, RetryPolicy

# Causation/liability/entitlement/drafting queries never become composites.
from ..programme_tools.registry import SHARED_NEGATIVE_TRIGGERS as _PROG_NEG

# evidence_explain intentionally allows "why ... delay ... evidence" — build a
# reduced negative list for it (still blocks who-caused / entitlement).
_STRICT_NEG = list(_PROG_NEG)
_EVIDENCE_NEG = [p for p in _PROG_NEG
                 if p not in (r"\bdelay events?\b",)]  # keep all; delay wording ok


@dataclass(frozen=True)
class IntentSpec:
    intent_id: str
    description: str
    positive_triggers: List[str]
    negative_triggers: List[str] = field(default_factory=lambda: list(_STRICT_NEG))
    risk: str = "medium"          # "high" forces an explicit trust-guard step
    slots: List[str] = field(default_factory=list)

    def matches(self, q: str) -> bool:
        if any(re.search(p, q) for p in self.negative_triggers):
            return False
        return any(re.search(p, q) for p in self.positive_triggers)


CAPABILITIES: Dict[str, CapabilitySpec] = {
    "programme.inventory": CapabilitySpec("programme.inventory", "XER revision inventory", True),
    "programme.dcma_14_point": CapabilitySpec("programme.dcma_14_point", "DCMA scorecard", True),
    "programme.milestone_shift": CapabilitySpec("programme.milestone_shift", "milestone drift", True),
    "delay.chronology": CapabilitySpec(
        "delay.chronology", "6.1-style chronology", False,
        RetryPolicy(max_retries=1, fallback="markdown")),
    "sql.metric": CapabilitySpec(
        "sql.metric", "deterministic table metric", True,
        RetryPolicy(max_retries=0, fallback="clarification")),
    "viz.bar_chart": CapabilitySpec(
        "viz.bar_chart", "bar chart from table", True,
        RetryPolicy(max_retries=0, fallback="table"), guards=["chart_guard"]),
    "viz.line_chart": CapabilitySpec(
        "viz.line_chart", "line chart from series", True,
        RetryPolicy(max_retries=0, fallback="table"), guards=["chart_guard"]),
    "narrative.guarded": CapabilitySpec(
        "narrative.guarded", "guarded narrative", False,
        RetryPolicy(max_retries=1, fallback="deterministic"),
        guards=["narrative_guard"]),
    "html.compose_section": CapabilitySpec(
        "html.compose_section", "deterministic html section", True,
        RetryPolicy(max_retries=0, fallback="markdown"), guards=["html_guard"]),
    "resolve.inputs": CapabilitySpec(
        "resolve.inputs", "input resolution", True,
        RetryPolicy(max_retries=0, fallback="clarification")),
    "guard.trust": CapabilitySpec(
        "guard.trust", "trust guard verification", False,
        RetryPolicy(max_retries=0, fallback="none"), guards=["trust_guard"]),
}

_CHART_WORD = r"(chart|graph|plot|visuali[sz]e|visual)"

COMPOSITE_INTENTS: Dict[str, IntentSpec] = {
    "composite.milestone_shift_visual": IntentSpec(
        intent_id="composite.milestone_shift_visual",
        description="Milestone drift + chart + guarded narrative",
        positive_triggers=[
            rf"milestone\w*\b.*\b(as|with)?\s*a?\s*{_CHART_WORD}",
            rf"{_CHART_WORD}\b.*\bmilestone",
            rf"(completion|key)\s+dates?.*{_CHART_WORD}",
            rf"{_CHART_WORD}\b.*(completion|key)\s+dates?",
        ],
        # milestone wording is REQUIRED here, so drop the generic 'milestone'
        # negative that the programme-shared list carries for other routes.
        negative_triggers=[p for p in _STRICT_NEG if "milestone" not in p],
        slots=["chart_type"],
    ),
    "composite.sql_metric_chart": IntentSpec(
        intent_id="composite.sql_metric_chart",
        description="Deterministic Excel metric + bar chart",
        positive_triggers=[
            rf"(bar|line)?\s*{_CHART_WORD}\s+(of|for|showing)\b.*"
            r"(manpower|workers?|trade|equipment|machin\w+|utili[sz]ation|ipc|progress)",
            rf"(plot|chart|graph)\b.*(manpower|equipment|workers?|utili[sz]ation)\b.*"
            r"(by|per)\s+\w+",
            rf"show\s+(the\s+)?(manpower|equipment|utili[sz]ation).*(by|per)\s+\w+.*"
            rf"(as|in)\s+a?\s*{_CHART_WORD}",
        ],
        negative_triggers=[p for p in _STRICT_NEG
                           if p not in (r"\bmanpower\b", r"equipment")],
        slots=["chart_type", "schema", "period", "dimension"],
    ),
    "composite.programme_compare": IntentSpec(
        intent_id="composite.programme_compare",
        description="Baseline vs current comparison + explanation",
        positive_triggers=[
            r"compare\b.*baseline\b.*(current|update|latest)",
            r"compare\b.*(programmes?|schedules?|revisions?)\b.*(explain|shift|change)",
            r"(baseline|current)\b.*(vs|versus)\b.*(baseline|current|update)",
        ],
        slots=[],
    ),
    "composite.chronology_html": IntentSpec(
        intent_id="composite.chronology_html",
        description="6.1-style chronology rendered as an HTML report section",
        positive_triggers=[
            r"(chronolog\w*|6\.1)\b.*\b(html|report\s+section)",
            r"(html|report\s+section)\b.*\bchronolog",
        ],
        negative_triggers=[p for p in _STRICT_NEG if "chronolog" not in p],
        slots=["event_title"],
    ),
    "composite.context_to_section": IntentSpec(
        intent_id="composite.context_to_section",
        description="Turn the previous result into an HTML report section",
        positive_triggers=[
            r"(make|turn|convert|format)\s+(this|that|it)\s+(into|as)\s+"
            r"(an?\s+)?(html\s+)?report\s+section",
            r"create\s+this\s+as\s+an?\s+html\s+report",
        ],
        slots=[],
    ),
    "composite.dcma_latest": IntentSpec(
        intent_id="composite.dcma_latest",
        description="DCMA on the latest programme (auto-resolved)",
        positive_triggers=[
            r"\bdcma\b.*(latest|most\s+recent|newest|last)\s+"
            r"(update\s+)?(programme|program|schedule|xer|revision)",
            r"(latest|most\s+recent)\s+(programme|schedule).*\bdcma\b",
        ],
        negative_triggers=[p for p in _STRICT_NEG if "dcma" not in p],
        slots=[],
    ),
    "composite.evidence_explain": IntentSpec(
        intent_id="composite.evidence_explain",
        description="Evidence-backed delay explanation (high risk, "
                    "trust-guarded; never a causation finding)",
        positive_triggers=[
            r"(why|explain)\b.*delay\w*\b.*(evidence|supporting\s+documents?|"
            r"show\s+.*documents?)",
            r"(evidence|supporting\s+documents?)\b.*(why|explain)\b.*delay",
        ],
        negative_triggers=_EVIDENCE_NEG,
        risk="high",
        slots=[],
    ),
}


def match_composite(query: str) -> Optional[Dict[str, str]]:
    """Deterministic intent match on the lowercased current question."""
    q = (query or "").lower()
    for spec in COMPOSITE_INTENTS.values():
        if spec.matches(q):
            return {"kind": "composite", "id": spec.intent_id}
    return None
