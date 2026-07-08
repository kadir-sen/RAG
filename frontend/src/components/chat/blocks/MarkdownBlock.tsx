import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';
import type { MarkdownTextBlock } from '../../../types/api';

// Same table/emphasis styling as AssistantMessage's markdown renderer.
const markdownComponents: Components = {
  table: ({ children, ...props }) => (
    <div className="overflow-x-auto my-3 rounded-lg border border-[var(--border)]">
      <table className="w-full text-xs" {...props}>{children}</table>
    </div>
  ),
  thead: ({ children, ...props }) => (
    <thead className="bg-[var(--bg-primary)]" {...props}>{children}</thead>
  ),
  th: ({ children, ...props }) => (
    <th className="px-3 py-2 text-left text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wider border-b border-[var(--border)]" {...props}>
      {children}
    </th>
  ),
  td: ({ children, ...props }) => (
    <td className="px-3 py-2 text-[var(--text-primary)] border-b border-[var(--border)]/50" {...props}>
      {children}
    </td>
  ),
  strong: ({ children, ...props }) => (
    <strong className="text-[var(--text-primary)] font-semibold" {...props}>{children}</strong>
  ),
};

export default function MarkdownBlock({ block }: { block: MarkdownTextBlock }) {
  return (
    <div className="prose prose-invert prose-sm max-w-none text-[var(--text-primary)]">
      <ReactMarkdown components={markdownComponents}>{block.text}</ReactMarkdown>
    </div>
  );
}
