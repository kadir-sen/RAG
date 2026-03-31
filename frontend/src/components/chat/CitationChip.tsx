import { memo } from 'react';
import type { Citation } from '../../types/api';

interface Props {
  citation: Citation;
  onClick: () => void;
}

function CitationChip({ citation, onClick }: Props) {
  const name =
    citation.doc_name.length > 25
      ? citation.doc_name.slice(0, 22) + '...'
      : citation.doc_name;

  return (
    <button
      onClick={onClick}
      title={`${citation.doc_name} — ${citation.anchor}`}
      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-[var(--accent)]/10 border border-[var(--accent)]/30 text-xs text-[var(--accent)] hover:bg-[var(--accent)]/20 hover:border-[var(--accent)] hover:shadow-md transition-all cursor-pointer"
    >
      <span className="w-2 h-2 rounded-full bg-[var(--accent)]" />
      <span className="underline decoration-dotted underline-offset-2">{name}</span>
      {citation.score != null && (
        <span className="text-[var(--text-secondary)]">
          {Math.round(citation.score * 100)}%
        </span>
      )}
    </button>
  );
}

export default memo(CitationChip);
