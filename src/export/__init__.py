"""Report export — report sections to downloadable PDF/DOCX artifacts.

A leaf package on purpose: it imports orchestration.html_section (pure stdlib)
and programme_tools' schemas/paths, and nothing imports back into it. Putting
this under orchestration would have put `import fitz` on the hot composite
import path and risked a cycle with programme_tools.
"""

from .artifacts import persist_blobs, safe_filename
from .section import FORMATS, render_section, section_artifacts

__all__ = ["persist_blobs", "safe_filename", "section_artifacts",
           "render_section", "FORMATS"]
