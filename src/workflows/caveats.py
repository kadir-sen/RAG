"""Central caveat catalogue + aggregation.

Stable constant strings so routing/caveat tests can assert exactly, and so the
same wording is reused across workflows rather than re-authored inline.
"""

from __future__ import annotations

from typing import List

# ── Programme / XER resolution ───────────────────────────────
NO_XER = ("No programme (.xer) files are available; upload a Primavera P6 "
          "export first.")
ONE_XER_ONLY = ("Only one dated programme revision exists; a comparison needs "
                "at least two.")
LATEST_AMBIGUOUS = ("Multiple programmes share the latest data date; the "
                    "selection was not unambiguous.")
BASELINE_INFERRED = ("Baseline inferred from the earliest data date — confirm "
                     "this is the contract baseline.")
MILESTONE_MAPPING_UNCONFIRMED = ("Fuzzy milestone matches were surfaced for "
                                 "analyst confirmation, not auto-merged.")

# ── Excel / SQL data ─────────────────────────────────────────
NO_COMPATIBLE_EXCEL = ("No compatible Excel/data table was found for this "
                       "metric; nothing was charted.")
LOW_CONFIDENCE_SCHEMA = ("The Excel schema mapping is low-confidence; verify "
                         "the columns before relying on this result.")

# ── LLM / guards availability ────────────────────────────────
LLM_NARRATIVE_UNAVAILABLE = ("Narrative generated deterministically; the LLM "
                             "was unavailable.")
TRUST_GUARD_UNAVAILABLE = ("Trust-Guard verification was skipped; treat the "
                           "summary as unverified.")

# ── Interpretation limits (never overclaim) ──────────────────
MOVEMENT_NOT_CAUSATION = ("Programme movement describes schedule change only; "
                          "it is not evidence of causation or responsibility.")
DCMA_HEALTH_NOT_DELAY = ("DCMA is a schedule-health check, not proof of delay "
                         "or entitlement.")
CHRONOLOGY_PRELIMINARY = ("This chronology is an evidence-based preliminary "
                          "draft for analyst review, not a finding.")
ANALYST_REVIEW_ENTITLEMENT = ("Analyst review is required before any "
                              "entitlement, liability or claim use.")


def aggregate(*lists: List[str]) -> List[str]:
    """Merge caveat lists, drop empties, dedupe, preserve first-seen order."""
    seen: set = set()
    out: List[str] = []
    for lst in lists:
        for c in lst or []:
            c = (c or "").strip()
            if c and c not in seen:
                seen.add(c)
                out.append(c)
    return out
