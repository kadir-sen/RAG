"""A chat answer → .docx.

Until now an answer could only leave the browser as clipboard text, or — for a
SQL answer — as a CSV of its preview rows. Anything a user wanted to hand on had
to be copied out by hand, losing the citations, the page anchors and any table.

The document is built to be handed on: the question it answers, the answer, the
citations with the page each one points at, the SQL and its rows when there are
any, and a provenance stamp. Everything the reader needs to check it.

Two honesty rules are baked in, both learned from what this codebase got wrong
before:

  * **It never claims a row count it does not have.** A restored conversation
    keeps only the first 20 preview rows and no total (chat_orchestrator persists
    `preview_rows`, and the count is recomputed from their length on reload), so
    the document says "the first N rows this answer retained" unless the caller
    passes a total it actually knows.
  * **It says what it flattened.** Markdown this parser does not handle is listed
    in the footer when it occurs, rather than disappearing quietly.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from . import docx_kit as kit
from .markdown_blocks import parse, spans

# Hard caps. The endpoint renders text the caller supplied, so the limits are
# what keep a formatter from becoming a way to make the box do arbitrary work.
MAX_ANSWER_CHARS = 200_000
MAX_CITATIONS = 500
MAX_ROWS = 2_000
MAX_COLS = 60

_CODE_BG = "F3F4F6"


def _runs(paragraph, text: str, size: int, colour: str) -> None:
    """Write inline markdown spans as runs on an existing paragraph."""
    Pt, RGBColor, _ = kit.shared()
    for chunk, style in spans(text):
        if not chunk:
            continue
        run = paragraph.add_run(chunk)
        run.font.size = Pt(size)
        run.font.color.rgb = RGBColor.from_string(colour)
        if style == "bold":
            run.font.bold = True
        elif style == "italic":
            run.font.italic = True
        elif style == "code":
            run.font.name = "Consolas"
    return None


def _table(doc, header: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
    """A real Word table. The chat cannot draw one — react-markdown has no
    remark-gfm here, so a pipe table reaches the screen as literal text — which
    makes this the one place the file is better than the browser."""
    Pt, RGBColor, _ = kit.shared()
    header = [str(h) for h in header][:MAX_COLS]
    if not header:
        return
    table = doc.add_table(rows=1, cols=len(header))
    table.style = "Table Grid"
    for cell, head in zip(table.rows[0].cells, header):
        cell.paragraphs[0].paragraph_format.space_after = Pt(0)
        kit.mono(cell.paragraphs[0].add_run(head.upper()), size=8,
                 colour=kit.INK, bold=True)
    for row in rows[:MAX_ROWS]:
        cells = table.add_row().cells
        values = list(row)[:len(header)]
        values += [""] * (len(header) - len(values))   # pad, never drop
        for cell, value in zip(cells, values):
            cell.paragraphs[0].paragraph_format.space_after = Pt(0)
            run = cell.paragraphs[0].add_run("" if value is None else str(value))
            run.font.size = Pt(8)
            run.font.color.rgb = RGBColor.from_string(kit.INK)


def _render_markdown(doc, text: str) -> None:
    Pt, RGBColor, Cm = kit.shared()
    for block in parse(text):
        kind = block["type"]

        if kind == "heading":
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(8)
            p.paragraph_format.space_after = Pt(2)
            run = p.add_run(block["text"])
            run.font.bold = True
            run.font.size = Pt(max(10, 15 - block["level"]))
            run.font.color.rgb = RGBColor.from_string(kit.INK)

        elif kind == "para":
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(5)
            _runs(p, block["text"], 10, kit.BODY)

        elif kind in ("bullet", "ordered"):
            style = "List Bullet" if kind == "bullet" else "List Number"
            try:
                p = doc.add_paragraph(style=style)
            except KeyError:                 # template without the list styles
                p = doc.add_paragraph()
                p.paragraph_format.left_indent = Cm(0.8)
            p.paragraph_format.space_after = Pt(2)
            if block.get("depth"):
                p.paragraph_format.left_indent = Cm(1.6)
            _runs(p, block["text"], 10, kit.BODY)

        elif kind == "quote":
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.8)
            p.paragraph_format.space_after = Pt(5)
            _runs(p, block["text"], 10, kit.MUTED)

        elif kind == "code":
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.5)
            p.paragraph_format.space_after = Pt(6)
            kit.mono(p.add_run(block["text"]), size=9, colour=kit.INK)

        elif kind == "rule":
            kit.rule(doc)

        elif kind == "table":
            _table(doc, block["header"], block["rows"])
            doc.add_paragraph().paragraph_format.space_after = Pt(4)


def _citations(doc, citations: Sequence[Dict[str, Any]]) -> None:
    kit.rule(doc)
    kit.label(doc, f"Sources · {len(citations)}")
    Pt, RGBColor, Cm = kit.shared()
    for c in citations[:MAX_CITATIONS]:
        name = str(c.get("doc_name") or c.get("file_name") or "").strip()
        if not name:
            continue
        # "page_37" → "p.37". The anchor is what makes a citation checkable, so
        # it travels with the name rather than being dropped as plumbing.
        anchor = str(c.get("anchor") or "")
        page = anchor.split("_", 1)[1] if anchor.startswith("page_") else ""
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(1)
        kit.mono(p.add_run(f"{name}{f'  p.{page}' if page else ''}"),
                 size=9, colour=kit.INK)
        snippet = str(c.get("snippet") or "").strip()
        if snippet:
            sp = doc.add_paragraph()
            sp.paragraph_format.left_indent = Cm(0.5)
            sp.paragraph_format.space_after = Pt(5)
            run = sp.add_run(f"“{snippet}”")
            run.font.size = Pt(9)
            run.font.italic = True
            run.font.color.rgb = RGBColor.from_string(kit.MUTED)


def build_answer_docx(
    question: str,
    answer: str,
    *,
    citations: Optional[Sequence[Dict[str, Any]]] = None,
    sql: str = "",
    table_columns: Optional[Sequence[str]] = None,
    table_rows: Optional[Sequence[Sequence[Any]]] = None,
    total_rows: Optional[int] = None,
    title_text: str = "",
) -> bytes:
    """Render one answer as a Word document.

    `total_rows` is the query's true row count when the caller knows it. When it
    is None the document says how many rows it is showing and makes no claim
    about the query — a restored answer only ever kept 20 and has no memory of
    the total, and inventing one would be worse than admitting it.
    """
    answer = (answer or "")[:MAX_ANSWER_CHARS]
    citations = list(citations or [])
    rows = list(table_rows or [])
    cols = list(table_columns or [])

    doc = kit.new_document()
    kit.label(doc, "COAir · answer")
    kit.title(doc, title_text or "Project record — answer")

    if question:
        p = doc.add_paragraph()
        Pt, RGBColor, _ = kit.shared()
        p.paragraph_format.space_after = Pt(6)
        run = p.add_run(question.strip())
        run.font.size = Pt(11)
        run.font.italic = True
        run.font.color.rgb = RGBColor.from_string(kit.MUTED)
    kit.rule(doc)

    if answer.strip():
        _render_markdown(doc, answer)
    else:
        kit.body(doc, "This answer had no text.", colour=kit.MUTED)

    if sql.strip():
        kit.rule(doc)
        kit.label(doc, "Query")
        p = doc.add_paragraph()
        kit.mono(p.add_run(sql.strip()), size=9, colour=kit.INK)

    if cols and rows:
        kit.label(doc, "Result")
        _table(doc, cols, rows)
        shown = min(len(rows), MAX_ROWS)
        if total_rows is not None and total_rows > shown:
            kit.footer_note(doc, f"Showing {shown} of {total_rows} rows.")
        elif total_rows is None:
            # Deliberately not "of N" — see the docstring.
            kit.footer_note(
                doc, f"Showing the first {shown} row{'' if shown == 1 else 's'} "
                     f"this answer retained.")

    if citations:
        _citations(doc, citations)

    dropped = []
    if len(answer) >= MAX_ANSWER_CHARS:
        dropped.append("the answer was longer than this export carries")
    if len(rows) > MAX_ROWS:
        dropped.append(f"only the first {MAX_ROWS} rows are included")
    if len(cols) > MAX_COLS:
        dropped.append(f"only the first {MAX_COLS} columns are included")
    if len(citations) > MAX_CITATIONS:
        dropped.append(f"only the first {MAX_CITATIONS} sources are listed")
    if dropped:
        kit.footer_note(doc, "Note — " + "; ".join(dropped) + ".")

    kit.stamp(doc)
    return kit.save(doc)


def answer_filename(question: str) -> str:
    """A name taken from the question, so a folder of these stays legible."""
    stem = " ".join((question or "").split())[:60]
    return kit.safe_filename("COAir", "answer", stem) + ".docx"
