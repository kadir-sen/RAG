"""The markdown reader behind the Word export.

Pure — no python-docx, no I/O — so these assert on the blocks directly.

The table cases carry the weight. The chat renders answers with react-markdown
and no remark-gfm, so a pipe table currently reaches the reader as literal
"| a | b |" text; the export draws it properly, which is the one place the file
is better than the screen. That only holds if a real table is recognised and a
sentence with a pipe in it is not, so both directions are pinned here.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.markdown_blocks import parse, spans  # noqa: E402


def _types(md):
    return [b["type"] for b in parse(md)]


class TestBlockShapes:
    def test_headings_keep_their_level(self):
        out = parse("# One\n\n### Three")
        assert out == [{"type": "heading", "level": 1, "text": "One"},
                       {"type": "heading", "level": 3, "text": "Three"}]

    def test_paragraphs_join_wrapped_lines(self):
        out = parse("The delay was caused\nby a water main.")
        assert out == [{"type": "para",
                        "text": "The delay was caused by a water main."}]

    def test_blank_line_separates_paragraphs(self):
        assert _types("one\n\ntwo") == ["para", "para"]

    def test_bullets_and_nesting(self):
        out = parse("- top\n    - nested\n* also top")
        assert [(b["type"], b["depth"]) for b in out] == [
            ("bullet", 0), ("bullet", 1), ("bullet", 0)]

    def test_ordered_lists_keep_their_numbers(self):
        out = parse("1. first\n2. second\n10) tenth")
        assert [b["number"] for b in out] == [1, 2, 10]

    def test_quote_code_and_rule(self):
        out = parse("> quoted\n\n```sql\nSELECT 1\n```\n\n---")
        assert _types("> quoted\n\n```sql\nSELECT 1\n```\n\n---") == [
            "quote", "code", "rule"]
        code = [b for b in out if b["type"] == "code"][0]
        assert code["text"] == "SELECT 1" and code["lang"] == "sql"

    def test_fenced_code_keeps_markdown_inside_it_literal(self):
        """A fence is verbatim — a '# ' inside it is not a heading."""
        out = parse("```\n# not a heading\n- not a bullet\n```")
        assert out == [{"type": "code", "text": "# not a heading\n- not a bullet",
                        "lang": ""}]

    def test_empty_and_whitespace_input(self):
        assert parse("") == [] and parse("   \n\n  ") == []

    def test_an_indented_line_continues_its_list_item(self):
        """Found by the real-answer test below. The model wraps long list items,
        and without this the tail became a stray paragraph outside the list —
        which reads as broken in a document someone hands on."""
        out = parse("1. a delay from the planned start date\n"
                    "   of 01/08/08 until 18/02/09.")
        assert out == [{"type": "ordered", "number": 1, "depth": 0,
                        "text": "a delay from the planned start date "
                                "of 01/08/08 until 18/02/09."}]

    def test_an_unindented_line_after_a_list_item_stays_a_paragraph(self):
        """Unindented lazy continuation is indistinguishable from the next
        paragraph; joining there would merge text the writer separated."""
        assert _types("- item\nA new sentence.") == ["bullet", "para"]

    def test_continuation_does_not_swallow_a_nested_item(self):
        out = parse("- top\n    - nested")
        assert [(b["type"], b["depth"]) for b in out] == [("bullet", 0), ("bullet", 1)]


class TestTables:
    def test_a_pipe_table_becomes_a_table(self):
        md = ("| Document | Page |\n"
              "|---|---|\n"
              "| CEC00381196_PART1.pdf | 5 |\n"
              "| WED00000533.pdf | 25 |")
        out = parse(md)
        assert len(out) == 1 and out[0]["type"] == "table"
        assert out[0]["header"] == ["Document", "Page"]
        assert out[0]["rows"] == [["CEC00381196_PART1.pdf", "5"],
                                  ["WED00000533.pdf", "25"]]

    def test_prose_with_a_pipe_is_not_a_table(self):
        """The separator row is the whole signal. Without it this is a sentence."""
        out = parse("The trade-off was cost | schedule, and neither won.")
        assert _types("The trade-off was cost | schedule, and neither won.") == ["para"]
        assert "cost | schedule" in out[0]["text"]

    def test_a_ragged_row_is_padded_not_dropped(self):
        md = "| a | b | c |\n|---|---|---|\n| 1 | 2 |\n| 1 | 2 | 3 | 4 |"
        rows = parse(md)[0]["rows"]
        assert rows == [["1", "2", ""], ["1", "2", "3"]]

    def test_a_table_ends_at_a_blank_line(self):
        md = "| a | b |\n|---|---|\n| 1 | 2 |\n\nAfterwards."
        assert _types(md) == ["table", "para"]

    def test_table_without_outer_pipes(self):
        out = parse("a | b\n--- | ---\n1 | 2")
        assert out[0]["header"] == ["a", "b"] and out[0]["rows"] == [["1", "2"]]


class TestInlineSpans:
    def test_bold_italic_and_code(self):
        assert list(spans("a **b** c *d* e `f`")) == [
            ("a ", ""), ("b", "bold"), (" c ", ""), ("d", "italic"),
            (" e ", ""), ("f", "code")]

    def test_underscore_forms(self):
        assert list(spans("__b__ and _i_")) == [
            ("b", "bold"), (" and ", ""), ("i", "italic")]

    def test_a_link_keeps_its_url_in_parentheses(self):
        """Printed reports outlive live links, so the URL travels as text."""
        assert list(spans("see [the report](https://x.test/r.pdf)")) == [
            ("see the report (https://x.test/r.pdf)", "")]

    def test_plain_text_is_one_span(self):
        assert list(spans("nothing special here")) == [("nothing special here", "")]

    def test_stray_asterisk_is_not_a_span(self):
        assert list(spans("2 * 3 = 6")) == [("2 * 3 = 6", "")]


class TestRealAnswerShape:
    """A production answer, abbreviated — the shape the exporter actually gets."""

    ANSWER = """The delay to the construction of the depot was caused by several factors:

1.  **Water Main and Delayed Site Access:** A delay from the planned start date
    of 01/08/08 until 18/02/09.
2.  **MUDFA Works:** Outstanding utility diversions in the same area.

| Cause | Period |
|---|---|
| Water main | 01/08/08 – 18/02/09 |
| MUDFA | ongoing |

> tie accepted responsibility for the access delay.
"""

    def test_it_parses_into_the_expected_sequence(self):
        assert _types(self.ANSWER) == [
            "para", "ordered", "ordered", "table", "quote"]

    def test_the_table_survives_intact(self):
        table = [b for b in parse(self.ANSWER) if b["type"] == "table"][0]
        assert table["header"] == ["Cause", "Period"]
        assert table["rows"] == [["Water main", "01/08/08 – 18/02/09"],
                                 ["MUDFA", "ongoing"]]

    def test_bold_inside_a_list_item_is_still_bold(self):
        first = [b for b in parse(self.ANSWER) if b["type"] == "ordered"][0]
        styles = [s for _, s in spans(first["text"])]
        assert "bold" in styles
