"""Sprint D — output-format router (English-only).

The product is English-only, so intent detection is English-only. These tests
pin the mapping from prompt → OutputPlan → block/artifact, and that an
unsupported export (PPTX) is reported as planned/unavailable rather than
crashing.
"""

import pytest

from src.planning import plan_output, is_export_available
from src.planning.output_planner import (DATA_TABLE, CHART, HTML_REPORT_SECTION,
                                          PDF_REPORT, DOCX_REPORT,
                                          PRESENTATION_DECK, DIRECT_ANSWER)


class TestInlineIntents:
    def test_table(self):
        p = plan_output("show manpower by trade in a table")
        assert p.output_intent == DATA_TABLE
        assert "data_table" in p.required_blocks

    def test_bar_chart(self):
        p = plan_output("draw a chart of cost by block")
        assert p.output_intent == CHART
        assert p.chart_type == "bar"
        assert "chart" in p.required_blocks

    def test_line_chart(self):
        p = plan_output("plot the cumulative progress trend over time")
        assert p.output_intent == CHART
        assert p.chart_type == "line"

    def test_html_report_section(self):
        p = plan_output("prepare an HTML report section on the delay")
        assert p.output_intent == HTML_REPORT_SECTION
        assert p.section_numbering is True
        assert "html_report_section" in p.required_blocks

    def test_direct_answer_default(self):
        p = plan_output("how many workers were on block B?")
        assert p.output_intent == DIRECT_ANSWER
        assert p.required_blocks == ["markdown_text"]

    def test_report_word_without_format_is_html_section(self):
        p = plan_output("management briefing on the crane delay")
        assert p.output_intent == HTML_REPORT_SECTION


class TestExportIntents:
    def test_pdf(self):
        p = plan_output("give me the delay analysis as a PDF")
        assert p.output_intent == PDF_REPORT
        assert p.export_format == "pdf" and p.export_available is True
        assert p.artifact_needed and "artifact_link" in p.required_blocks

    def test_docx(self):
        p = plan_output("export the report as a Word document")
        assert p.output_intent == DOCX_REPORT
        assert p.export_format == "docx" and p.export_available is True

    def test_export_beats_inline(self):
        # asks for a table AND a PDF → the packaged export wins
        p = plan_output("show it in a table and give me a PDF")
        assert p.output_intent == PDF_REPORT


class TestPresentationUnavailable:
    def test_pptx_planned_not_crash(self):
        p = plan_output("prepare a presentation deck of the findings")
        assert p.output_intent == PRESENTATION_DECK
        assert p.export_format == "pptx"
        assert p.export_available is False
        assert p.unavailable_note and "planned" in p.unavailable_note.lower()

    def test_is_export_available(self):
        assert is_export_available("pdf") is True
        assert is_export_available("docx") is True
        assert is_export_available("pptx") is False
        assert is_export_available(None) is False


class TestForensicAppendices:
    def test_forensic_adds_appendices_and_validation(self):
        p = plan_output("delay chronology report", is_forensic=True)
        assert p.source_appendix_required is True
        assert p.basis_appendix_required is True
        assert "validation_status" in p.required_blocks

    def test_non_forensic_no_appendices(self):
        p = plan_output("show cost by block in a table")
        assert p.source_appendix_required is False


class TestReportHandlerIntegration:
    """The report step honours an OutputSpec: a chart directive turns the
    produced {columns, rows} table into a chart block (values verbatim); a PPTX
    request degrades gracefully with the unavailable note; no directive → no
    chart (the data step already rendered the table)."""

    def _run(self, query, output=None):
        from src.planning.handlers import build_handlers
        from src.planning import SkillContext
        from src.planning.schemas import SubTask
        handlers = build_handlers(router=None)
        h = handlers["report.table_pack"]
        # New-shape table dict (as the data handlers now store it).
        store = {"comparison_table":
                 {"columns": ["proj", "cost"], "rows": [["P1", 10], ["P2", 7]]}}
        ctx = SkillContext(extra={"query": query})
        return h(SubTask(id="t", skill="report.table_pack", output=output),
                 store, ctx)

    def test_chart_directive_emits_chart_block(self):
        from src.planning.schemas import OutputSpec
        res = self._run("compare projects and draw a bar chart",
                        output=OutputSpec(kind="bar_chart", x="proj",
                                          series=["cost"]))
        types = {b["type"] for b in res.blocks}
        assert "chart" in types
        chart = next(b for b in res.blocks if b["type"] == "chart")
        assert chart["values"] == [10.0, 7.0]      # copied verbatim from table
        assert chart["categories"] == ["P1", "P2"]

    def test_line_chart_directive(self):
        from src.planning.schemas import OutputSpec
        res = self._run("cost over time as a line chart",
                        output=OutputSpec(kind="line_chart", x="proj",
                                          series=["cost"]))
        chart = next(b for b in res.blocks if b["type"] == "chart")
        assert chart["chart_type"] == "line"
        assert chart["series"][0]["points"][0] == {"x": "P1", "y": 10.0}

    def test_pptx_request_adds_graceful_caveat(self):
        res = self._run("compare projects and prepare a presentation deck")
        assert any("planned" in c.lower() for c in res.caveats)

    def test_no_directive_no_chart(self):
        res = self._run("compare projects in a table")
        assert all(b["type"] != "chart" for b in res.blocks)
