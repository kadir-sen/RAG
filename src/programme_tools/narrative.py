"""Narrative composer — turns a validated ToolResult into report prose.

The LLM sees ONLY the vendored prompt builders' serialization of the
deterministic output; every draft passes the narrative guard (max 1 rewrite),
and on repeated failure a deterministic fallback rendering ships instead.
The data is always delivered — only the prose is optional.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .guards.narrative_guard import GuardVerdict, check_narrative
from .schemas import STATUS_COMPLETE, ToolResult

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are drafting a factual summary of a deterministic construction-"
    "programme analysis. Use ONLY the figures, dates, activity IDs and "
    "findings present in the input. Do not compute new values, extrapolate, "
    "apportion blame, or assess entitlement or liability. Preserve the term "
    "'as-recorded' where it appears; never describe recorded dates as "
    "'as-built' facts. End with a 'Caveats' section reproducing every caveat "
    "verbatim. If the analysis is partial or failed, say so explicitly."
)


def _build_prompt(result: ToolResult, engine_ctx: Any) -> Optional[str]:
    """Route to the vendored prompt builder for this tool. engine_ctx carries
    the engine objects the builders expect (set by the adapters' callers)."""
    try:
        if result.tool_id == "programme.dcma_14_point" and engine_ctx:
            from .vendor.dcma.narrative import build_report_prompt
            return build_report_prompt(engine_ctx["data"], engine_ctx["results"])
        if result.tool_id == "programme.inventory" and engine_ctx:
            from .vendor.programme.narrative import build_inventory_prompt
            return build_inventory_prompt(engine_ctx["inventory"])
        if result.tool_id == "programme.milestone_shift" and engine_ctx:
            from .vendor.programme.narrative import build_milestone_prompt
            return build_milestone_prompt(engine_ctx["result"], engine_ctx["series"])
    except Exception as e:
        logger.warning(f"[ProgrammeNarrative] prompt build failed: {e}")
    return None


def deterministic_fallback(result: ToolResult) -> str:
    """LLM-free rendering — correct by construction."""
    lines = [result.summary]
    for t in result.tables:
        lines.append(f"- {t['title']}: {len(t['rows'])} row(s) — see the table below.")
    if result.status != STATUS_COMPLETE:
        lines.append(f"Note: this analysis is {result.status}.")
    if result.warnings:
        lines.append("\n**Warnings:**")
        lines += [f"- {w}" for w in result.warnings]
    if result.caveats:
        lines.append("\n**Caveats:**")
        lines += [f"- {c}" for c in result.caveats]
    return "\n".join(lines)


def compose_narrative(result: ToolResult, engine_ctx: Any = None,
                      use_llm: bool = True) -> str:
    """Draft + guard the narrative. Never raises; always returns usable text.

    Records the guard outcome in result.validation["narrative_guard"] so the
    report itself carries its validation audit trail."""
    def _audit(status: str, violations=None) -> None:
        result.validation["narrative_guard"] = {
            "status": status, "violations": list(violations or [])}

    if not use_llm or result.status == "failed":
        _audit("deterministic_only")
        return deterministic_fallback(result)

    prompt = _build_prompt(result, engine_ctx)
    if prompt is None:
        _audit("deterministic_only")
        return deterministic_fallback(result)

    last_violations: list = []
    try:
        from src import llm_client
        from src.config import GEMINI_MODEL_LITE
        from src.prompt_security import build_system_prompt

        draft = ""
        rewrite_note = ""
        for attempt in range(2):  # initial + max 1 rewrite
            resp = llm_client.generate_text(
                prompt + rewrite_note,
                system=build_system_prompt(_SYSTEM),
                model=GEMINI_MODEL_LITE,
                temperature=0.1,
                max_tokens=1500,
            )
            draft = (resp.text or "").strip()
            verdict: GuardVerdict = check_narrative(draft, result)
            if verdict.approved:
                _audit("approved" if attempt == 0 else "rewritten_then_approved")
                return draft
            last_violations = verdict.violations
            logger.info(f"[ProgrammeNarrative] guard rejected (attempt {attempt + 1}): "
                        f"{verdict.violations}")
            rewrite_note = (
                "\n\nYOUR PREVIOUS DRAFT WAS REJECTED for these violations — "
                "fix ALL of them without introducing new figures:\n- "
                + "\n- ".join(verdict.violations)
            )
        logger.warning("[ProgrammeNarrative] guard rejected twice → deterministic fallback")
        _audit("fallback_after_rejection", last_violations)
        note = ("_Automated narrative failed validation; showing computed "
                "results only._")
    except Exception as e:
        logger.warning(f"[ProgrammeNarrative] LLM narrative failed open: {e}")
        _audit("llm_unavailable")
        note = ("_Automated narrative is temporarily unavailable; showing "
                "computed results only._")
    return note + "\n\n" + deterministic_fallback(result)
