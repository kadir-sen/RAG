"""Delay-analysis method viability — MVP (deterministic data-availability screen).

Given the inputs actually present (baseline programme, programme updates,
confirmed delay events, served notices, contract mechanisms), reports which
recognised delay-analysis methods are *supportable by the available data*.

This is a DATA-AVAILABILITY screening only — method selection is a forensic and
often contractual judgement (SCL Protocol), and data being present does not make
a method appropriate. Every output says so and requires analyst review. No LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class Availability:
    baseline: bool = False
    programme_updates: bool = False   # >= 2 dated revisions
    confirmed_events: int = 0
    notices: int = 0
    contract_mechanisms: int = 0


# method → (label, required-availability predicate description)
_METHODS = [
    ("impacted_as_planned", "Impacted As-Planned",
     lambda a: a.baseline and a.confirmed_events > 0,
     "baseline programme + confirmed delay event(s)"),
    ("as_planned_vs_as_built", "As-Planned vs As-Built (as-recorded)",
     lambda a: a.baseline and a.programme_updates,
     "baseline + at least one later programme revision"),
    ("time_impact_analysis", "Time Impact Analysis (TIA)",
     lambda a: a.baseline and a.programme_updates and a.confirmed_events > 0,
     "baseline + updates + confirmed delay event(s)"),
    ("collapsed_as_built", "Collapsed As-Built (but-for)",
     lambda a: a.programme_updates and a.confirmed_events > 0,
     "an as-built/updated programme + confirmed delay event(s)"),
    ("windows_analysis", "Windows / Time-Slice Analysis",
     lambda a: a.programme_updates,
     "two or more dated programme revisions"),
]

STANDING_CAVEATS = [
    "This is a DATA-AVAILABILITY screening, not a recommendation: the presence "
    "of data does not make a method contractually or forensically appropriate.",
    "Method selection follows the SCL Delay & Disruption Protocol and the "
    "contract; an analyst must choose and justify the method.",
]


def assess(av: Availability) -> List[Dict]:
    """Return one row per method: viable + missing-inputs note."""
    rows = []
    for key, label, pred, needs in _METHODS:
        viable = bool(pred(av))
        rows.append({
            "method": label, "key": key, "viable": viable,
            "requires": needs,
            "status": "Data available" if viable else "Missing inputs",
        })
    return rows
