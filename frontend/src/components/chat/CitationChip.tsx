import { memo } from 'react';
import type { Citation } from '../../types/api';

interface Props {
  citation: Citation;
  onClick: () => void;
}

function iconForExt(name: string): string {
  const ext = name.slice(name.lastIndexOf('.')).toLowerCase();
  if (ext === '.msg' || ext === '.eml') return '✉';
  if (ext === '.xlsx' || ext === '.xls' || ext === '.csv') return '▦';
  return '▣';
}

/**
 * Inline citation chip rendered at the end of an assistant paragraph:
 *   "… Governing law: English law, London jurisdiction  📄 NDA.pdf"
 *
 * No bracket number, no percentage — just the file icon + name. Hover lifts
 * to accent colour.
 */
function CitationChip({ citation, onClick }: Props) {
  const name =
    citation.doc_name.length > 38
      ? citation.doc_name.slice(0, 35) + '…'
      : citation.doc_name;

  return (
    <button
      onClick={onClick}
      title={`${citation.doc_name} — ${citation.anchor}`}
      className="inline-flex items-center gap-1.5 align-baseline ml-2 px-2 py-0.5 rounded-md font-mono text-[11px] leading-tight border border-[var(--border)] bg-[rgba(255,255,255,0.02)] text-[var(--text-secondary)] hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors"
    >
      <span aria-hidden="true" className="text-[var(--text-muted)]">{iconForExt(citation.doc_name)}</span>
      <span className="truncate max-w-[18rem]">{name}</span>
    </button>
  );
}

export default memo(CitationChip);
