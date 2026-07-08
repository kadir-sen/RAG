"""Composite executor — whitelist runner dispatch.

Each composite intent has a fixed runner (no LLM-chosen plans). Runners build
blocks step by step with per-step guards/retries; a failed step degrades to
its fallback while the safe blocks still ship.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

from .schemas import CompositeResult

logger = logging.getLogger(__name__)


class RunContext:
    """Everything a runner may touch. No dynamic attribute magic."""

    def __init__(self, query: str, slots: Dict[str, Any], router: Any,
                 doc_ids: Optional[List[str]] = None,
                 context_artifact: Optional[dict] = None,
                 run_id: Optional[str] = None):
        self.query = query
        self.slots = slots or {}
        self.router = router
        self.doc_ids = doc_ids
        self.context_artifact = context_artifact
        self.run_id = run_id or uuid.uuid4().hex[:12]

    def report(self, kind: str, label: str, detail: str = "") -> None:
        try:
            from backend.tasks.query_progress import report_step
            report_step(kind, label, detail)
        except Exception:
            pass


# Whitelist: intent_id → runner. Populated lazily to avoid import cycles;
# nothing outside this mapping can ever run.
def _runners() -> Dict[str, Callable[[RunContext], CompositeResult]]:
    from . import runners
    return {
        "composite.milestone_shift_visual": runners.milestone_shift_visual,
        "composite.sql_metric_chart": runners.sql_metric_chart,
        "composite.programme_compare": runners.programme_compare,
        "composite.chronology_html": runners.chronology_html,
        "composite.context_to_section": runners.context_to_section,
        "composite.dcma_latest": runners.dcma_latest,
        "composite.evidence_explain": runners.evidence_explain,
    }


def run_composite(intent_id: str, query: str, slots: Dict[str, Any],
                  router: Any, doc_ids: Optional[List[str]] = None,
                  context_artifact: Optional[dict] = None,
                  run_id: Optional[str] = None) -> CompositeResult:
    """Execute one registered composite intent. Never raises."""
    runner = _runners().get(intent_id)
    if runner is None:
        return CompositeResult(
            intent_id=intent_id or "unknown", status="failed",
            answer=f"'{intent_id}' is not a registered capability.",
        )
    ctx = RunContext(query, slots, router, doc_ids, context_artifact, run_id)
    try:
        return runner(ctx)
    except Exception as e:
        logger.exception(f"[Orchestration] runner {intent_id} crashed")
        return CompositeResult(
            intent_id=intent_id, status="failed",
            answer="The requested analysis failed unexpectedly; please try "
                   f"again. ({e})",
        )
