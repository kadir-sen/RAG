# Vendored from delay-analysis-toolkit (https://github.com/altunozan/delay-analysis-toolkit,
# private, owner-authorized copy) on 2026-07-06. No upstream LICENSE file exists.
# Local modifications: absolute->relative import rewrite and LLM-backend removal only.
"""DCMA narrative PROMPT BUILDER (COAir-vendored, prompt-only).

Builds a forensic-analyst prompt from the deterministic DCMA check results.
The upstream multi-provider streaming backends AND the PROVIDERS registry
were removed in vendoring — the only LLM path in COAir is src/llm_client.py,
which consumes build_report_prompt's output.
"""

from __future__ import annotations


from .checks import CheckResult
from .rationale import CHECK_RATIONALE
from .xer_parser import XerData

SYSTEM_PROMPT = """\
You are an expert Forensic Delay Analyst and Project Controls Engineer
specializing in schedule diagnostics and delay analytics. Your role is to
analyze structured schedule metadata and generate high-quality, professional,
and contractually sound narratives.

Adhere strictly to the following principles:
1. Objectivity: Base all insights purely on the provided metrics. Do not
   extrapolate facts not supported by the numbers.
2. Technical Precision: Use correct project controls terminology (e.g.,
   driving logic, total float, constraints, critical path, out-of-sequence
   progress).
3. Strategic Insight: Focus on how schedule quality impacts project risk,
   critical path integrity, and potential claims exposure.
4. Balance: Report strengths with the same rigor as weaknesses. Where a
   metric passes its target, state what that soundness supports (e.g., a
   credible critical path, defensible float values); do not write a
   deficiencies-only account.
"""


# --------------------------------------------------------------------------- #
# Unified error type so the UI handles all providers the same way
# --------------------------------------------------------------------------- #
class NarrativeError(Exception):
    """Provider-agnostic failure with a user-facing message."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# --------------------------------------------------------------------------- #
# Prompt assembly (provider-independent)
# --------------------------------------------------------------------------- #
# Default report-section template. The UI lets the analyst edit this before
# generation; the objectivity rules in SYSTEM_PROMPT are not editable.
DEFAULT_TEMPLATE = """\
### 1. Executive Summary
- High-level overview of the health of this schedule — both what it does
well and where it falls short.
- The single greatest risk to the project's completion date based on these
metrics.

### 2. Schedule Strengths
- Analyze the passed checks: what each sound metric supports (e.g., dense
logic → credible network; few constraints → float values that can be relied
on; healthy relationship mix → realistic sequencing).
- State which analytical conclusions these strengths make defensible.

### 3. Schedule Quality & Integrity Diagnostics (DCMA Focus)
- Analyze each failed check: what the number means for THIS schedule, why the
DCMA target exists, and what structural weakness it exposes.
- Identify where weaknesses (missing logic, constraints, high float) may be
masking true critical-path visibility or distorting float.
- Name the specific affected activities where relevant.

### 4. Critical Issues & Interactions
- Identify the most critical issues in the programme and how the individual
failures compound each other (e.g., hard constraints + negative float,
dangling logic + high float).
- Evaluate the negative-float activities and what they imply for the
completion commitment.

### 5. Claims Exposure & Recommendations
- Assess how the current schedule quality would hold up in a delay claim or
forensic review — which aspects strengthen the position and which weaken it.
- Provide a prioritized, actionable correction list for the planning team."""


def build_report_prompt(
    data: XerData,
    results: list[CheckResult],
    template: str | None = None,
) -> str:
    """Assemble the user prompt from project metadata + check results."""
    proj = data.project
    lines: list[str] = []

    lines.append("<context>")
    lines.append(
        "You have been provided with DCMA 14-Point schedule diagnostic results "
        "for the project below. These metrics were calculated deterministically "
        "by a Python engine from the native Primavera P6 (XER) schedule file. "
        "Generate a comprehensive Schedule Analytics Report."
    )
    lines.append("</context>\n")

    lines.append("<project_metadata>")
    lines.append(f"Project: {proj.short_name if proj else 'Unknown'}")
    if proj and proj.data_date:
        lines.append(f"Data Date: {proj.data_date:%Y-%m-%d}")
    if proj and proj.scheduled_finish:
        lines.append(f"Scheduled Finish: {proj.scheduled_finish:%Y-%m-%d}")
    if proj and proj.must_finish:
        lines.append(f"Must Finish By: {proj.must_finish:%Y-%m-%d}")
    lines.append(f"Total Activities: {len(data.tasks)}")
    lines.append(f"Total Relationships: {len(data.relationships)}")
    lines.append("</project_metadata>\n")

    lines.append("<diagnostic_metrics>")
    for r in results:
        lines.append(f"Check {r.number} — {r.name} [{r.status.value}]")
        lines.append(f"  Metric: {r.metric_label} = {r.metric_value} "
                     f"(target {r.threshold})")
        lines.append(f"  Finding: {r.summary}")
        if r.na_reason:
            lines.append(f"  N/A reason: {r.na_reason}")
        if r.affected_ids:
            shown = ", ".join(r.affected_ids[:25])
            more = f" (+{len(r.affected_ids) - 25} more)" if len(r.affected_ids) > 25 else ""
            lines.append(f"  Affected activities: {shown}{more}")
        rationale = CHECK_RATIONALE.get(r.number)
        if rationale:
            lines.append(f"  DCMA rationale: {rationale}")
        lines.append("")
    lines.append("</diagnostic_metrics>\n")

    lines.append("<instructions>")
    lines.append(
        "Generate the report using the following markdown structure. Keep the "
        "tone professional and authoritative — clear enough for executive "
        "stakeholders while maintaining forensic depth.\n\n"
        + (template or DEFAULT_TEMPLATE) + "\n"
    )
    lines.append("</instructions>")

    return "\n".join(lines)


# NOTE (COAir vendoring): the provider streaming backends (_stream_anthropic/_stream_openai/
# _stream_gemini, stream_narrative, generate_narrative, PROVIDERS) were removed so the only
# LLM path in COAir is src/llm_client.py. Use build_report_prompt + COAir's llm_client.
