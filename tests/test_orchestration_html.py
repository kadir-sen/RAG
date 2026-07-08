"""HTML templater + sanitizer + guard: XSS matrix and round-trip checks."""

import pytest

from src.orchestration.html_section import (
    build_html_block, compose_section, html_guard, sanitize_html,
)


class TestSanitizerXSS:
    @pytest.mark.parametrize("payload", [
        '<script>alert(1)</script>',
        '<img src="https://evil.example/x.png">',
        '<img src="x" onerror="alert(1)">',
        '<a href="javascript:alert(1)">x</a>',
        '<iframe src="https://evil.example"></iframe>',
        '<style>body{display:none}</style>',
        '<div onclick="steal()">x</div>',
        '<img srcset="https://evil.example/x.png 1x">',
        '<object data="x"></object>',
        '<form action="https://evil.example"><input></form>',
        '<svg onload="alert(1)"></svg>',
        '<a href="https://phish.example">click</a>',
    ])
    def test_hostile_markup_neutralized(self, payload):
        out = sanitize_html(payload)
        low = out.lower()
        assert "<script" not in low
        assert "javascript:" not in low
        assert "onerror" not in low and "onclick" not in low and "onload" not in low
        assert "evil.example" not in low or "href" not in low
        assert "<iframe" not in low and "<object" not in low
        assert "srcset" not in low
        assert 'href="https://' not in low

    def test_entity_encoded_script_stays_inert(self):
        out = sanitize_html("&lt;script&gt;alert(1)&lt;/script&gt;")
        assert "<script" not in out

    def test_allowed_markup_survives(self):
        html = ('<div class="coair-report-body"><h2>Title</h2>'
                '<p><strong>bold</strong> text</p>'
                '<a href="/api/artifacts/r1/f.xlsx">file</a>'
                '<td colspan="2">x</td></div>')
        out = sanitize_html(html)
        assert "<h2>" in out and "<strong>" in out
        assert 'href="/api/artifacts/r1/f.xlsx"' in out

    def test_disallowed_class_stripped(self):
        out = sanitize_html('<div class="external-widget">x</div>')
        assert "external-widget" not in out


class TestTemplater:
    def _section(self, **kw):
        base = dict(
            title="Delayed Blockwork",
            narrative_markdown=("6.1.1 On 19 July 2023, JAMED raised concerns. "
                                "(L1.pdf, p.3)\n\nSecond paragraph."),
            tables=[{"title": "Chronology", "columns": ["Date", "Actor"],
                     "rows": [["19 July 2023", "JAMED"]]}],
            sources=[{"file_name": "L1.pdf", "page_number": 3}],
            caveats=["Statements are the parties' claims."],
            validation={"computation_guard": {"post": "passed"}},
            section_number="6.1",
        )
        base.update(kw)
        return base

    def test_round_trips_sanitizer_unchanged(self):
        html, fallback = compose_section(**self._section())
        assert sanitize_html(html) == html
        assert html_guard(html, [{"f": 1}], ["c"]) == []
        assert "6.1. Delayed Blockwork" in html
        assert 'class="coair-para-no"' in html
        assert "coair-sources" in html and "coair-caveats" in html
        assert "coair-validation" in html
        assert fallback.startswith("## 6.1. Delayed Blockwork")

    def test_hostile_narrative_is_escaped(self):
        html, _ = compose_section(**self._section(
            narrative_markdown='<script>alert(1)</script> **bold** claim'))
        assert "<script" not in html
        assert "&lt;script&gt;" in html
        assert "<strong>bold</strong>" in html
        assert sanitize_html(html) == html

    def test_build_html_block_happy(self):
        blk = build_html_block("T", "6.1.1 On 19 July 2023, X stated. (f.pdf, p.1)",
                               sources=[{"file_name": "f.pdf", "page_number": 1}],
                               caveats=["c"])
        assert blk["type"] == "html_report_section"
        assert blk["sanitized"] is True
        assert blk["fallback_markdown"]

    def test_guard_failure_falls_back_to_markdown(self, monkeypatch):
        import src.orchestration.html_section as hs
        monkeypatch.setattr(hs, "html_guard",
                            lambda *a, **k: ["forced violation"])
        blk = hs.build_html_block("T", "narrative", caveats=["c"])
        assert blk["type"] == "markdown_text"
        assert "narrative" in blk["text"]
