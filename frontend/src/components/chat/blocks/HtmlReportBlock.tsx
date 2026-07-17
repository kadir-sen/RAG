import { useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import type { HtmlReportSectionBlock } from '../../../types/api';
import { sanitizeReportHtml } from '../../../utils/sanitizeReportHtml';

/** Renders an html report section. The backend builds this markup with a
 * deterministic templater and an allowlist sanitizer, and always ships a
 * markdown fallback; we sanitize again here so the injection point has its own
 * defense rather than trusting the payload. Styling is scoped via the
 * .coair-report-section class (globals.css). */
export default function HtmlReportBlock({ block }: { block: HtmlReportSectionBlock }) {
  const html = useMemo(
    () => (block.html ? sanitizeReportHtml(block.html) : ''),
    [block.html],
  );

  // Empty html, or html that was nothing but unsafe markup, falls back to the
  // markdown the backend guarantees alongside every section.
  if (!html.trim()) {
    return (
      <div className="prose prose-invert prose-sm max-w-none text-[var(--text-primary)]">
        <ReactMarkdown>{block.fallback_markdown}</ReactMarkdown>
      </div>
    );
  }
  return (
    <div className="my-3 rounded-lg border border-[var(--border)] bg-[var(--bg-primary)]/40 p-4">
      <div
        className="coair-report-section"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
}
