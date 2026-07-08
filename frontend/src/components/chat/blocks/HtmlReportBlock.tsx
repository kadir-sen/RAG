import ReactMarkdown from 'react-markdown';
import type { HtmlReportSectionBlock } from '../../../types/api';

/** Renders a SERVER-SANITIZED html report section. The backend guarantees the
 * html passed a strict allowlist sanitizer (no scripts/handlers/external
 * resources) and always ships a markdown fallback. Styling is scoped via the
 * .coair-report-section class (globals.css). */
export default function HtmlReportBlock({ block }: { block: HtmlReportSectionBlock }) {
  if (!block.html) {
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
        // Safe by construction: html is produced by a deterministic backend
        // templater and re-verified by the sanitizer diff check (html guard).
        dangerouslySetInnerHTML={{ __html: block.html }}
      />
    </div>
  );
}
