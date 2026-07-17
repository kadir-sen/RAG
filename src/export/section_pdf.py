"""Report section → PDF, via PyMuPDF's Story (HTML) engine.

Reuses html_section.compose_section rather than laying the page out again, so
the PDF is the same document the user saw on screen by construction: same
section order, same 200-row table cap, same escaping, same sources/caveats
blocks. A second layout implementation would drift the first time someone edits
the templater.

Feeding it that HTML is not "the LLM wrote HTML": compose_section is a
deterministic templater that html.escape's every text node, and html_guard
re-checks its output with a sanitize diff.
"""

from __future__ import annotations

import io
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# A4 in points, with a margin wide enough for the tables to breathe.
_PAGE = (595, 842)
_MARGIN = 54

# Maps the coair-* classes the templater emits onto print styling. Screen CSS
# (globals.css) is dark-themed and irrelevant here.
_CSS = """
body { font-family: sans-serif; font-size: 9pt; color: #111; }
h2 { font-size: 14pt; margin: 0 0 8pt 0; }
h4 { font-size: 10pt; margin: 10pt 0 4pt 0; }
p { margin: 0 0 6pt 0; line-height: 1.4; }
table { width: 100%; border-collapse: collapse; font-size: 8pt; margin: 6pt 0; }
th { text-align: left; border-bottom: 1px solid #999; padding: 3pt; }
td { border-bottom: 1px solid #ddd; padding: 3pt; }
.coair-para-no { font-weight: bold; }
.coair-sources { font-size: 7.5pt; color: #555; margin-top: 8pt; }
.coair-caveats { font-size: 7.5pt; margin-top: 8pt; }
.coair-validation { font-size: 7pt; color: #666; margin-top: 6pt; }
"""


def render_section_pdf(title: str, narrative_markdown: str,
                       tables: Optional[List[Dict[str, Any]]] = None,
                       sources: Optional[List[Dict[str, Any]]] = None,
                       caveats: Optional[List[str]] = None,
                       validation: Optional[Dict[str, Any]] = None,
                       section_number: str = "") -> bytes:
    """Render a report section to PDF bytes. Signature mirrors compose_section."""
    import fitz

    from src.orchestration.html_section import compose_section

    html, _ = compose_section(title, narrative_markdown, tables=tables,
                              sources=sources, caveats=caveats,
                              validation=validation,
                              section_number=section_number)

    story = fitz.Story(html=html, user_css=_CSS)
    buf = io.BytesIO()
    writer = fitz.DocumentWriter(buf)
    rect = fitz.Rect(_MARGIN, _MARGIN, _PAGE[0] - _MARGIN, _PAGE[1] - _MARGIN)

    more = True
    pages = 0
    while more:
        dev = writer.begin_page(fitz.Rect(0, 0, *_PAGE))
        more, _ = story.place(rect)
        story.draw(dev)
        writer.end_page()
        pages += 1
        if pages > 200:  # runaway guard; a section is never this long
            logger.warning("[ExportPDF] stopped at 200 pages")
            break
    writer.close()
    return buf.getvalue()
