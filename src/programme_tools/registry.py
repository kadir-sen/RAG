"""Programme Tool Registry — the contract layer between routing and engines.

The router may only select tool_ids present here; a query routes to a tool
iff at least one positive trigger matches AND no negative trigger matches.
Preconditions are checked at execution time by the handler — an unmet
precondition yields a user clarification, never a silent fallback to RAG.

Adding a future tool (variance, critical path) is pure data: a ToolSpec entry
plus an adapter registered in executor._ADAPTERS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ToolInput:
    name: str
    type: str                 # "xer_files" | "string" | ...
    required: bool
    description: str
    missing_message: str      # user-facing clarification when unmet


@dataclass(frozen=True)
class ToolSpec:
    tool_id: str
    title: str
    description: str
    inputs: List[ToolInput]
    output_schema: str
    positive_triggers: List[str]          # regex, matched on lowercased query
    negative_triggers: List[str] = field(default_factory=list)
    min_xer_files: int = 1

    def matches(self, query_lower: str) -> bool:
        if any(re.search(p, query_lower) for p in self.negative_triggers):
            return False
        return any(re.search(p, query_lower) for p in self.positive_triggers)


# Queries about causation/entitlement/correspondence belong to the document /
# Trust-Guard path, never to a deterministic programme engine.
SHARED_NEGATIVE_TRIGGERS: List[str] = [
    r"chronolog", r"delay event", r"\bnotices?\b", r"\bletters?\b",
    r"correspondence", r"\bemails?\b",
    r"who (caused|is responsible|was responsible)", r"\bblame", r"entitle",
    r"\bclaims?\b", r"\beot\b", r"culpab", r"liab",
]

_XER_INPUT = ToolInput(
    name="xer_files", type="xer_files", required=True,
    description="Uploaded Primavera P6 .xer export(s)",
    missing_message="Please upload at least one XER programme file to run this analysis.",
)

REGISTRY: Dict[str, ToolSpec] = {
    "programme.inventory": ToolSpec(
        tool_id="programme.inventory",
        title="Programme Inventory",
        description="Catalogue uploaded XER revisions: baseline/current "
                    "designation, data dates, counts, missing inputs.",
        inputs=[_XER_INPUT],
        output_schema="revisions table + missing-input caveats + xlsx",
        positive_triggers=[
            r"programme (inventory|intake|register)",
            r"program inventory",
            r"(what|which) (programmes?|schedules?|xer)",
            r"list .*(revisions?|xer)",
            r"baseline.*(current|identify)",
            r"inventory.*(xer|programme|schedule)",
        ],
        negative_triggers=SHARED_NEGATIVE_TRIGGERS,
        min_xer_files=1,
    ),
    "programme.dcma_14_point": ToolSpec(
        tool_id="programme.dcma_14_point",
        title="DCMA 14-Point Programme Health Check",
        description="Deterministic DCMA-style schedule quality checks on one "
                    "XER file: logic, leads/lags, constraints, float, "
                    "durations, CPLI, BEI.",
        inputs=[_XER_INPUT],
        output_schema="14-row scorecard + affected activities + xlsx",
        positive_triggers=[
            r"\bdcma\b",
            r"14[- ]point",
            r"schedule (health|quality|integrity)( check| assessment)?",
            r"programme (health|quality)( check| assessment)?",
            r"(missing|dangling) logic",
            r"negative float",
            r"hard constraints?",
            r"leads? and lags?",
        ],
        negative_triggers=SHARED_NEGATIVE_TRIGGERS,
        min_xer_files=1,
    ),
    "programme.milestone_shift": ToolSpec(
        tool_id="programme.milestone_shift",
        title="Milestone Shift Tracker",
        description="Milestone forecast/actual drift across XER revisions; "
                    "fuzzy matches surfaced for analyst confirmation, never "
                    "auto-merged.",
        inputs=[ToolInput(
            name="xer_files", type="xer_files", required=True,
            description="At least two P6 .xer revisions",
            missing_message="Milestone shift tracking requires at least two "
                            "XER revisions.",
        )],
        output_schema="shift table + needs-confirmation table + line chart + xlsx",
        positive_triggers=[
            r"milestone (movements?|shifts?|slips?|track\w*|drift\w*)",
            r"(track|show|compare).*milestones?",
            r"(completion|key) dates?.*(moved|slip|shift)",
            r"how (has|did|have) .*milestones?",
        ],
        negative_triggers=SHARED_NEGATIVE_TRIGGERS,
        min_xer_files=2,
    ),
    "programme.variance": ToolSpec(
        tool_id="programme.variance",
        title="As-Planned vs As-Recorded Variance",
        description="Compares a baseline programme against the latest recorded "
                    "one, grouped by a P6 activity-code dimension, reporting "
                    "each group's start/finish slippage.",
        inputs=[ToolInput(
            name="xer_files", type="xer_files", required=True,
            description="A baseline and at least one later .xer revision",
            missing_message="Variance analysis requires a baseline and a later "
                            "recorded XER revision (at least two).",
        )],
        output_schema="variance table + finish-slip bar chart + xlsx",
        positive_triggers=[
            r"as[- ]?planned (vs\.?|versus|against) as[- ]?(recorded|built)",
            r"\bvariance\b.*(analysis|programme|schedule|activity|wbs)",
            r"planned (vs\.?|versus) (recorded|actual|as[- ]?built)",
            r"(slippage|slip) by (activity|code|wbs|zone|area|trade)",
        ],
        negative_triggers=SHARED_NEGATIVE_TRIGGERS,
        min_xer_files=2,
    ),
    "programme.critical_path": ToolSpec(
        tool_id="programme.critical_path",
        title="Baseline Critical Path",
        description="Traces the planned critical (longest) path of a programme "
                    "by backward driving-logic, with a float-based fallback.",
        inputs=[ToolInput(
            name="xer_files", type="xer_files", required=True,
            description="At least one .xer programme (the baseline)",
            missing_message="Critical path analysis requires a programme XER.",
        )],
        output_schema="critical-path activity table + xlsx",
        positive_triggers=[
            r"(baseline |planned )?critical path",
            r"longest path",
            r"driving (path|logic|activities)",
            r"what('?s| is) (on|driving) the critical path",
        ],
        negative_triggers=SHARED_NEGATIVE_TRIGGERS,
        min_xer_files=1,
    ),
    "programme.comparison": ToolSpec(
        tool_id="programme.comparison",
        title="Revision Comparison / Change Log",
        description="Diffs two programme revisions like a Claim Digger — "
                    "added/deleted/renamed activities, duration/logic/lag/"
                    "constraint/calendar changes, and retrospective actual-date "
                    "changes.",
        inputs=[ToolInput(
            name="xer_files", type="xer_files", required=True,
            description="Two .xer revisions to diff",
            missing_message="Revision comparison requires two programme XER "
                            "revisions.",
        )],
        output_schema="change-category summary + detail tables",
        positive_triggers=[
            r"(compare|diff|comparison of) .*(revisions?|programmes?|schedules?|updates?)",
            r"change log",
            r"claim digg\w+",
            r"what changed between (the )?(two )?(programmes?|revisions?|updates?)",
            r"retrospective (changes?|actual)",
        ],
        negative_triggers=SHARED_NEGATIVE_TRIGGERS,
        min_xer_files=2,
    ),
    "programme.progress": ToolSpec(
        tool_id="programme.progress",
        title="Progress S-curve",
        description="Planned vs as-recorded cumulative progress; slippage is "
                    "the horizontal offset between the curves.",
        inputs=[ToolInput(
            name="xer_files", type="xer_files", required=True,
            description="A baseline and at least one later update",
            missing_message="A progress curve needs a baseline and a later "
                            "update (two dated XER revisions).",
        )],
        output_schema="planned/recorded S-curve line chart + summary table",
        positive_triggers=[
            r"(progress|s)[- ]?curve",
            r"planned (vs\.?|versus) (actual|recorded) progress",
            r"cumulative progress",
            r"how far (behind|ahead) .*(plan|programme|schedule)",
        ],
        negative_triggers=SHARED_NEGATIVE_TRIGGERS,
        min_xer_files=2,
    ),
}

WORKFLOW_ID = "report.preliminary_programme_analysis_pack"
WORKFLOW_TRIGGERS: List[str] = [
    r"(preliminary|prelim)\w*.*(programme|program|schedule).*(analysis|report|pack)",
    r"programme analysis (report|pack)",
    r"(generate|create|produce|build).*(programme|schedule) (analysis|health) (report|pack)",
]


def match_query(query: str) -> Optional[Dict[str, str]]:
    """Deterministic intent match. Returns {"kind": "workflow"|"tool",
    "id": ...} or None. Workflow triggers win over single tools."""
    q = (query or "").lower()
    if not any(re.search(p, q) for p in SHARED_NEGATIVE_TRIGGERS):
        if any(re.search(p, q) for p in WORKFLOW_TRIGGERS):
            return {"kind": "workflow", "id": WORKFLOW_ID}
    for spec in REGISTRY.values():
        if spec.matches(q):
            return {"kind": "tool", "id": spec.tool_id}
    return None
