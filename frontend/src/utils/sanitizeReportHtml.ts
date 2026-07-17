import DOMPurify from 'dompurify';

/**
 * Client-side sanitizer for html_report_section blocks.
 *
 * This is defense in depth, not the primary defense. The backend builds this
 * HTML with a deterministic templater that escapes every text node, runs it
 * through an allowlist sanitizer, and fails the block to markdown if the two
 * disagree (src/orchestration/html_section.py). What this layer buys us is a
 * second, independent check at the point of injection — it holds if the
 * backend regresses, if a block is served by something other than the
 * templater, or if the response is tampered with in transit.
 *
 * The allowlist mirrors html_section.py's _ALLOWED_TAGS / _attr_allowed. Keep
 * the two in sync: anything the templater legitimately emits and this drops
 * renders as unstyled or missing content, which is why the scoped classes
 * (coair-*) and table tags below are load-bearing for globals.css.
 */

// Mirrors _ALLOWED_TAGS (html_section.py).
const ALLOWED_TAGS = [
  'h1', 'h2', 'h3', 'h4', 'p', 'ul', 'ol', 'li', 'table', 'thead', 'tbody',
  'tr', 'th', 'td', 'strong', 'em', 'span', 'div', 'blockquote', 'hr', 'a',
  'sup', 'small', 'img', 'br',
];

// Mirrors the attribute names _attr_allowed can return true for. Per-tag and
// per-value rules are enforced in the hook below, since ALLOWED_ATTR is global.
const ALLOWED_ATTR = ['class', 'style', 'href', 'src', 'colspan', 'rowspan', 'alt'];

const CLASS_PREFIX = 'coair-';
const STYLE_RE = /^text-align:\s*(left|right|center);?$/;
const ARTIFACT_PREFIX = '/api/artifacts/';
const IMG_DATA_PREFIX = 'data:image/png;base64,';

let hookInstalled = false;

/** Per-tag attribute rules mirroring _attr_allowed. DOMPurify's ALLOWED_ATTR
 *  is tag-agnostic, so the value/tag pairing is enforced here. */
function installHook() {
  if (hookInstalled) return;
  DOMPurify.addHook('afterSanitizeAttributes', (node) => {
    const el = node as Element;
    if (!el.getAttribute) return;
    const tag = el.tagName?.toLowerCase();

    const href = el.getAttribute('href');
    if (href !== null && !(tag === 'a' && (href.startsWith(ARTIFACT_PREFIX) || href.startsWith('#')))) {
      el.removeAttribute('href');
    }

    const src = el.getAttribute('src');
    if (src !== null && !(tag === 'img' && (src.startsWith(IMG_DATA_PREFIX) || src.startsWith(ARTIFACT_PREFIX)))) {
      el.removeAttribute('src');
    }

    // Only our own scoped classes survive — this both matches the backend and
    // stops injected markup from borrowing app styling.
    const cls = el.getAttribute('class');
    if (cls !== null && !cls.split(/\s+/).filter(Boolean).every((c) => c.startsWith(CLASS_PREFIX))) {
      el.removeAttribute('class');
    }

    const style = el.getAttribute('style');
    if (style !== null && !STYLE_RE.test(style.trim())) {
      el.removeAttribute('style');
    }

    for (const attr of ['colspan', 'rowspan']) {
      const v = el.getAttribute(attr);
      if (v !== null && !(/^\d+$/.test(v) && (tag === 'th' || tag === 'td'))) {
        el.removeAttribute(attr);
      }
    }
  });
  hookInstalled = true;
}

/** Sanitize a report section's HTML. Returns markup safe to inject. */
export function sanitizeReportHtml(html: string): string {
  installHook();
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    // Drop these entirely rather than unwrapping them — content inside a
    // <script>/<style> is not text we want surfacing as visible characters.
    FORBID_CONTENTS: ['script', 'style', 'iframe', 'object', 'embed', 'form',
                      'svg', 'math', 'link', 'meta', 'noscript'],
    ALLOW_DATA_ATTR: false,
    ALLOW_ARIA_ATTR: false,
  });
}
