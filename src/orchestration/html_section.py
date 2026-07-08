"""HTML report section: deterministic templater + allowlist sanitizer + guard.

The LLM never writes raw HTML: compose_section builds the markup from
structured inputs with html.escape on every text node, so injection is
impossible by construction. The sanitizer still runs as defense-in-depth —
ANY difference between templated and sanitized output fails the html guard
and the block falls back to markdown.
"""

from __future__ import annotations

import html as html_lib
import logging
import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_ALLOWED_TAGS = {
    "h1", "h2", "h3", "h4", "p", "ul", "ol", "li", "table", "thead", "tbody",
    "tr", "th", "td", "strong", "em", "span", "div", "blockquote", "hr", "a",
    "sup", "small", "img", "br",
}
_DROP_WITH_CONTENT = {"script", "style", "iframe", "object", "embed", "form",
                      "svg", "math", "link", "meta", "noscript"}
_VOID_TAGS = {"hr", "br", "img"}
_ALLOWED_CLASSES_PREFIX = "coair-"
_STYLE_RE = re.compile(r"^text-align:\s*(left|right|center);?$")


def _attr_allowed(tag: str, name: str, value: str) -> bool:
    name = name.lower()
    if name.startswith("on") or name in ("srcset", "target", "formaction"):
        return False
    if name == "href" and tag == "a":
        return value.startswith("/api/artifacts/") or value.startswith("#")
    if name == "src" and tag == "img":
        return value.startswith("data:image/png;base64,") or \
            value.startswith("/api/artifacts/")
    if name in ("colspan", "rowspan") and tag in ("th", "td"):
        return value.isdigit()
    if name == "class":
        return all(c.startswith(_ALLOWED_CLASSES_PREFIX)
                   for c in value.split())
    if name == "style":
        return bool(_STYLE_RE.match(value.strip()))
    return False


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: List[str] = []
        self._drop_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if self._drop_depth:
            if tag in _DROP_WITH_CONTENT:
                self._drop_depth += 1
            return
        if tag in _DROP_WITH_CONTENT:
            self._drop_depth += 1
            return
        if tag not in _ALLOWED_TAGS:
            return  # unwrap: drop tag, keep content
        clean = [(n, v) for n, v in attrs
                 if v is not None and _attr_allowed(tag, n, v)]
        attr_str = "".join(f' {n}="{html_lib.escape(v, quote=True)}"'
                           for n, v in clean)
        self.out.append(f"<{tag}{attr_str}>"
                        if tag not in _VOID_TAGS else f"<{tag}{attr_str}/>")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self._drop_depth:
            if tag in _DROP_WITH_CONTENT:
                self._drop_depth -= 1
            return
        if tag in _ALLOWED_TAGS and tag not in _VOID_TAGS:
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self._drop_depth:
            self.out.append(html_lib.escape(data))


def sanitize_html(raw: str) -> str:
    p = _Sanitizer()
    p.feed(raw or "")
    p.close()
    return "".join(p.out)


# ── Deterministic templater ──────────────────────────────────

def _esc(s: Any) -> str:
    return html_lib.escape(str(s if s is not None else ""))


def _md_paragraphs(md: str) -> str:
    """Minimal markdown→HTML: blank-line paragraphs, **bold**, leading
    paragraph-number highlighting. No markdown library, fully escaped."""
    out = []
    for para in re.split(r"\n\s*\n", (md or "").strip()):
        text = _esc(para.strip())
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"^(#+\s*)", "", text)
        m = re.match(r"^(\d+\.\d+\.\d+)\s+", text)
        if m:
            text = (f'<span class="coair-para-no">{m.group(1)}</span>'
                    + text[m.end():])
        text = text.replace("\n", "<br/>")
        out.append(f"<p>{text}</p>")
    return "".join(out)


def compose_section(title: str, narrative_markdown: str,
                    tables: Optional[List[Dict[str, Any]]] = None,
                    sources: Optional[List[Dict[str, Any]]] = None,
                    caveats: Optional[List[str]] = None,
                    validation: Optional[Dict[str, Any]] = None,
                    section_number: str = "") -> Tuple[str, str]:
    """Deterministic HTML section. Returns (html, fallback_markdown)."""
    parts: List[str] = ['<div class="coair-report-body">']
    heading = f"{section_number + '. ' if section_number else ''}{title}"
    parts.append(f"<h2>{_esc(heading)}</h2>")
    parts.append(_md_paragraphs(narrative_markdown))

    for t in tables or []:
        parts.append(f"<h4>{_esc(t.get('title', ''))}</h4>")
        parts.append("<table><thead><tr>")
        for c in t.get("columns") or []:
            parts.append(f"<th>{_esc(c)}</th>")
        parts.append("</tr></thead><tbody>")
        for row in (t.get("rows") or [])[:200]:
            parts.append("<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in row)
                         + "</tr>")
        parts.append("</tbody></table>")

    if sources:
        parts.append('<div class="coair-sources"><strong>Sources</strong><ul>')
        for s in sources[:30]:
            label = f"{s.get('file_name', '?')}, p.{s.get('page_number', 1)}"
            parts.append(f"<li>{_esc(label)}</li>")
        parts.append("</ul></div>")

    if caveats:
        parts.append('<div class="coair-caveats"><strong>Caveats</strong><ul>')
        for c in caveats[:15]:
            parts.append(f"<li>{_esc(c)}</li>")
        parts.append("</ul></div>")

    if validation:
        guard_bits = []
        for name, v in (validation or {}).items():
            state = v.get("post") or v.get("status") or "?" \
                if isinstance(v, dict) else str(v)
            guard_bits.append(f"{name}: {state}")
        parts.append(f'<div class="coair-validation">Validation — '
                     f"{_esc(' · '.join(guard_bits))}</div>")

    parts.append("</div>")
    html = "".join(parts)

    fb_lines = [f"## {heading}", "", narrative_markdown.strip()]
    if caveats:
        fb_lines += ["", "**Caveats:**"] + [f"- {c}" for c in caveats]
    return html, "\n".join(fb_lines)


def html_guard(html: str, sources: Optional[list],
               caveats: Optional[list]) -> List[str]:
    """Sanitize-diff + structural checks. Empty list = passed."""
    violations: List[str] = []
    sanitized = sanitize_html(html)
    if sanitized != html:
        violations.append("html changed under sanitization (unsafe content)")
    if sources and "coair-sources" not in html:
        violations.append("sources missing from the rendered section")
    if caveats and "coair-caveats" not in html:
        violations.append("caveats missing from the rendered section")
    return violations


def build_html_block(title: str, narrative_markdown: str, **kw) -> dict:
    """Compose + guard; on guard failure return a markdown fallback block."""
    html, fallback = compose_section(title, narrative_markdown, **kw)
    violations = html_guard(html, kw.get("sources"), kw.get("caveats"))
    if violations:
        logger.warning(f"[HtmlSection] guard failed: {violations}")
        return {"type": "markdown_text", "block_id": "html-fallback",
                "text": fallback}
    return {"type": "html_report_section", "block_id": "section",
            "title": title, "html": html, "fallback_markdown": fallback,
            "sanitized": True}
