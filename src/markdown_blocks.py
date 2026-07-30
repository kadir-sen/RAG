"""Markdown → a flat block list, for the .docx exporter.

Only the subset the chat actually produces and the browser actually shows — plus
one thing it does not. The chat renders answers with react-markdown and **no
remark-gfm** (see frontend/package.json), so a pipe table in an answer currently
reaches the reader as literal ``| a | b |`` text, and the table styles in
AssistantMessage.tsx are dead code. This parser draws pipe tables properly, which
makes the exported file better than the screen rather than a lossy copy of it.
Worth knowing, and worth fixing on the chat side separately.

FLATTENED, deliberately: inline HTML, images, footnotes, reference-style links,
task lists, nested tables, definition lists. Each is either absent from these
answers or meaningless in a Word paragraph, and a half-supported feature that
silently drops content is worse than one documented as unsupported.

No new dependency. A markdown library would be a container rebuild for a subset
this small, and a line-oriented reader is pure — no python-docx, no I/O — so the
tests can assert on the blocks directly.
"""

from __future__ import annotations

import re
from typing import Dict, Iterator, List, Tuple

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_ORDERED = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_QUOTE = re.compile(r"^>\s?(.*)$")
_HRULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_FENCE = re.compile(r"^\s*```(\w*)\s*$")
# A table row is a line with at least two pipe-separated cells. The separator row
# beneath the header is what distinguishes a table from a sentence with a pipe in
# it, so we never commit to a table without seeing one.
_TABLE_ROW = re.compile(r"^\s*\|?(.+\|.+?)\|?\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")


def _cells(line: str) -> List[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse(md: str) -> List[Dict]:
    """Blocks, in order. Each is one of:

        {"type": "heading", "level": 1..6, "text": str}
        {"type": "para",    "text": str}
        {"type": "bullet",  "text": str, "depth": 0|1}
        {"type": "ordered", "text": str, "depth": 0|1, "number": int}
        {"type": "quote",   "text": str}
        {"type": "code",    "text": str, "lang": str}
        {"type": "rule"}
        {"type": "table",   "header": [str], "rows": [[str]]}
    """
    lines = (md or "").replace("\r\n", "\n").split("\n")
    out: List[Dict] = []
    para: List[str] = []
    i = 0

    def flush() -> None:
        if para:
            text = " ".join(para).strip()
            if text:
                out.append({"type": "para", "text": text})
            para.clear()

    while i < len(lines):
        line = lines[i]

        fence = _FENCE.match(line)
        if fence:
            flush()
            lang, buf, i = fence.group(1), [], i + 1
            while i < len(lines) and not _FENCE.match(lines[i]):
                buf.append(lines[i])
                i += 1
            out.append({"type": "code", "text": "\n".join(buf), "lang": lang})
            i += 1
            continue

        # Look one line ahead before committing to a table, so "cost | schedule"
        # in prose stays prose.
        if (i + 1 < len(lines) and _TABLE_ROW.match(line)
                and _TABLE_SEP.match(lines[i + 1])):
            flush()
            header = _cells(line)
            i += 2
            rows: List[List[str]] = []
            while i < len(lines) and lines[i].strip() and _TABLE_ROW.match(lines[i]):
                row = _cells(lines[i])
                # A ragged row is padded, not dropped: a missing trailing cell is
                # a typo in the model's output, not a reason to lose the row.
                rows.append((row + [""] * len(header))[:len(header)])
                i += 1
            out.append({"type": "table", "header": header, "rows": rows})
            continue

        if not line.strip():
            flush()
            i += 1
            continue

        if _HRULE.match(line):
            flush()
            out.append({"type": "rule"})
            i += 1
            continue

        m = _HEADING.match(line)
        if m:
            flush()
            out.append({"type": "heading", "level": len(m.group(1)),
                        "text": m.group(2).strip()})
            i += 1
            continue

        m = _QUOTE.match(line)
        if m:
            flush()
            out.append({"type": "quote", "text": m.group(1).strip()})
            i += 1
            continue

        m = _ORDERED.match(line)
        if m:
            flush()
            out.append({"type": "ordered", "text": m.group(3).strip(),
                        "depth": 1 if len(m.group(1)) >= 2 else 0,
                        "number": int(m.group(2))})
            i += 1
            continue

        m = _BULLET.match(line)
        if m:
            flush()
            out.append({"type": "bullet", "text": m.group(2).strip(),
                        "depth": 1 if len(m.group(1)) >= 2 else 0})
            i += 1
            continue

        # Lazy continuation: an indented line straight after a list item belongs
        # to that item. The model wraps long items this way constantly —
        #
        #     1.  **Water main:** a delay from the planned start date
        #         of 01/08/08 until 18/02/09.
        #
        # and without this the second line becomes a stray paragraph sitting
        # outside the list, which is exactly the kind of thing that reads as
        # broken in a document someone hands on. Only *indented* continuation is
        # taken: unindented lazy continuation is indistinguishable from the next
        # paragraph, and guessing there would join text the writer separated.
        if (not para and out and out[-1]["type"] in ("bullet", "ordered")
                and line[:1].isspace()):
            out[-1]["text"] = f"{out[-1]['text']} {line.strip()}".strip()
            i += 1
            continue

        para.append(line.strip())
        i += 1

    flush()
    return out


# ── inline spans ────────────────────────────────────────────────────────
# Links become "text (url)". python-docx has no first-class hyperlink and
# hand-rolling w:hyperlink for a report that will be read on paper as often as on
# screen is not worth it — the URL in parentheses survives printing, a live link
# does not.
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_SPANS = re.compile(r"(\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_|`[^`]+`)")


def spans(text: str) -> Iterator[Tuple[str, str]]:
    """(text, style) pairs; style is one of "", "bold", "italic", "code"."""
    text = _LINK.sub(lambda m: f"{m.group(1)} ({m.group(2)})", text or "")
    for part in _SPANS.split(text):
        if not part:
            continue
        if len(part) > 4 and part.startswith("**") and part.endswith("**"):
            yield part[2:-2], "bold"
        elif len(part) > 4 and part.startswith("__") and part.endswith("__"):
            yield part[2:-2], "bold"
        elif len(part) > 2 and part.startswith("`") and part.endswith("`"):
            yield part[1:-1], "code"
        elif len(part) > 2 and part[0] in "*_" and part[-1] == part[0]:
            yield part[1:-1], "italic"
        else:
            yield part, ""
