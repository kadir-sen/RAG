"""Output router (Sprint D) — decide the OUTPUT FORMAT of an answer.

Routing today decides which *analysis* runs; format is inferred ad-hoc from
scattered English regexes in the composite registry. This module is the single
source of truth for output-format intent: given an (English) prompt it returns
an OutputPlan naming the block types to build, whether a downloadable artifact
is needed, and which export format.

English-only by product decision — the app's files, inputs, and outputs are
always English, so there is no multilingual intent detection here.

It never renders anything itself: it maps intent onto the existing 8-block
contract (backend/models/blocks.py) and the existing exporters
(export/section_pdf.py, section_docx.py). PPTX/presentation is recognized but
reported as planned/unavailable — a graceful message, never a crash.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

# Output modes.
DIRECT_ANSWER = "direct_answer"
DATA_TABLE = "data_table"
CHART = "chart"
HTML_REPORT_SECTION = "html_report_section"
PDF_REPORT = "pdf_report"
DOCX_REPORT = "docx_report"
PRESENTATION_DECK = "presentation_deck"

# Which export formats actually render today (see export/section.py FORMATS).
_AVAILABLE_EXPORTS = {"pdf", "docx"}

_CHART_RE = re.compile(r"\b(chart|graph|plot|visuali[sz]e|visual)\b")
_BAR_RE = re.compile(r"\bbar\b")
_LINE_RE = re.compile(r"\bline\b|\btrend\b|\bover time\b")
_TABLE_RE = re.compile(r"\b(as a table|in a table|tabular|table form|as tables|"
                       r"in tables)\b")
_HTML_RE = re.compile(r"\b(html|report section|formatted report)\b")
_PDF_RE = re.compile(r"\bpdf\b")
_DOCX_RE = re.compile(r"\b(docx|word document|word doc|as word|in word|\.docx)\b")
_PPTX_RE = re.compile(r"\b(presentation|slide deck|slides|powerpoint|pptx|deck)\b")
_REPORT_RE = re.compile(r"\b(report|briefing|management summary|memo)\b")


@dataclass
class OutputPlan:
    output_intent: str = DIRECT_ANSWER
    required_blocks: List[str] = field(default_factory=list)
    artifact_needed: bool = False
    export_format: Optional[str] = None       # pdf | docx | pptx | None
    export_available: bool = True
    chart_type: Optional[str] = None          # bar | line
    section_numbering: bool = False
    source_appendix_required: bool = False
    basis_appendix_required: bool = False
    unavailable_note: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "output_intent": self.output_intent,
            "required_blocks": self.required_blocks,
            "artifact_needed": self.artifact_needed,
            "export_format": self.export_format,
            "export_available": self.export_available,
            "chart_type": self.chart_type,
            "section_numbering": self.section_numbering,
            "source_appendix_required": self.source_appendix_required,
            "basis_appendix_required": self.basis_appendix_required,
            "unavailable_note": self.unavailable_note,
        }


def plan_output(query: str, is_forensic: bool = False) -> OutputPlan:
    """Map an English prompt to an OutputPlan.

    Export intents (PDF/DOCX/PPTX) win over inline intents (they imply the whole
    answer is packaged); among inline intents, an explicit chart beats a table
    beats an HTML section. A formal 'report/briefing' with no explicit format
    becomes an HTML report section with appendices. Forensic answers always
    carry the source + basis-of-analysis appendices."""
    q = f" {(query or '').lower()} "

    plan = OutputPlan()

    # ── Export intents (packaged artifact) ──
    if _PPTX_RE.search(q):
        # Recognized but not built — graceful, never a crash.
        plan.output_intent = PRESENTATION_DECK
        plan.export_format = "pptx"
        plan.export_available = False
        plan.artifact_needed = True
        plan.unavailable_note = (
            "Presentation/PPTX export is planned but not available yet; "
            "I can provide the same content as a PDF or DOCX report instead.")
        plan.required_blocks = ["html_report_section", "caveats"]
    elif _PDF_RE.search(q):
        plan.output_intent = PDF_REPORT
        plan.export_format = "pdf"
        plan.artifact_needed = True
        plan.required_blocks = ["html_report_section", "artifact_link", "caveats"]
    elif _DOCX_RE.search(q):
        plan.output_intent = DOCX_REPORT
        plan.export_format = "docx"
        plan.artifact_needed = True
        plan.required_blocks = ["html_report_section", "artifact_link", "caveats"]

    # ── Inline intents ──
    elif _CHART_RE.search(q):
        plan.output_intent = CHART
        plan.chart_type = "line" if _LINE_RE.search(q) else "bar"
        plan.required_blocks = ["chart", "data_table", "caveats"]
    elif _TABLE_RE.search(q):
        plan.output_intent = DATA_TABLE
        plan.required_blocks = ["data_table", "caveats"]
    elif _HTML_RE.search(q):
        plan.output_intent = HTML_REPORT_SECTION
        plan.section_numbering = True
        plan.required_blocks = ["html_report_section", "caveats"]
    elif _REPORT_RE.search(q):
        # A formal 'report/briefing' without an explicit format → HTML section.
        plan.output_intent = HTML_REPORT_SECTION
        plan.section_numbering = True
        plan.required_blocks = ["html_report_section", "caveats"]
    else:
        plan.output_intent = DIRECT_ANSWER
        plan.required_blocks = ["markdown_text"]

    # ── Forensic answers always carry provenance appendices ──
    if is_forensic:
        plan.source_appendix_required = True
        plan.basis_appendix_required = True
        if "validation_status" not in plan.required_blocks:
            plan.required_blocks.append("validation_status")

    return plan


def is_export_available(fmt: Optional[str]) -> bool:
    return bool(fmt) and fmt in _AVAILABLE_EXPORTS
