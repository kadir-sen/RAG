"""Query-pattern memory (read-side).

Learns which workflow a class of questions historically resolved to, from the
telemetry the executor already writes (`workflow_runs`). It returns a *secondary*
signal for the planner: consulted only AFTER the deterministic registry match,
and it can only ever point at a WorkflowId that is registered AND available — it
can never invent a workflow or override a deterministic match. Low signal → None
(the planner falls through to normal classification), never a silent guess.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# A pattern must be seen at least this many times and be this dominant among a
# signature's non-failed runs before it is allowed to influence routing.
MIN_SAMPLES = 3
MIN_DOMINANCE = 0.75
_GOOD_STATUSES = {"success", "partial"}

# High-risk / out-of-scope intents that memory must NEVER route to a workflow,
# no matter how dominant the history — causation / entitlement / liability /
# letter drafting belong to the guarded document path, not a deterministic
# workflow. Reuses the same denylist the programme/delay registries enforce.
_NEGATIVE_GUARD = re.compile(
    r"who\s+(caused|is\s+responsible|was\s+responsible)|\bblame|\bentitle|"
    r"\bliab|culpab|\beot\s+claim|draft\s+a?\s*(reply|letter|response)|"
    r"\bwho\s+caused", re.IGNORECASE)


def suggest(query: str, corpus: str = "") -> Optional[Dict[str, Any]]:
    """Best historical workflow for a query's signature, or None.

    Returns {workflow_id, confidence, sample_count} only when a single
    registered+available workflow dominates the successful history for this
    query signature above the thresholds. Never raises."""
    try:
        from .workflow_telemetry import query_signature, runs_for_query_signature
        from ..workflows.registry import is_available
        from ..workflows.types import WorkflowId

        # High-risk intents are never routed by memory (defence in depth: the
        # deterministic planner already returns None for these).
        if _NEGATIVE_GUARD.search(query or ""):
            logger.debug("[QueryPatterns] suppressed: high-risk negative match")
            return None

        sig = query_signature(query)
        if not sig:
            return None
        rows = runs_for_query_signature(sig)  # [{workflow_id, status, count}]
        if not rows:
            logger.debug(f"[QueryPatterns] no history for signature '{sig}'")
            return None

        good: Dict[str, int] = {}
        total_good = 0
        for r in rows:
            if r.get("status") in _GOOD_STATUSES:
                wid = r.get("workflow_id", "")
                good[wid] = good.get(wid, 0) + int(r.get("count", 0))
                total_good += int(r.get("count", 0))
        if total_good < MIN_SAMPLES or not good:
            return None

        wid, count = max(good.items(), key=lambda kv: kv[1])
        dominance = count / total_good
        if count < MIN_SAMPLES or dominance < MIN_DOMINANCE:
            return None

        # Registry validation: the signal can only point at a real, runnable
        # workflow — never invent one, never resurrect a planned/unavailable id.
        try:
            wid_enum = WorkflowId(wid)
        except ValueError:
            return None
        if not is_available(wid_enum):
            return None

        return {"workflow_id": wid_enum, "confidence": round(dominance, 3),
                "sample_count": count}
    except Exception as e:
        logger.debug(f"[QueryPatterns] suggest failed: {e}")
        return None
