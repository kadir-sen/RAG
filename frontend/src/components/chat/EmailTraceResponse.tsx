import type { RelatedDoc } from '../../types/api';
import type { ViewerDoc } from '../../stores/uiStore';

interface Props {
  docs: RelatedDoc[];
  onDocClick: (doc: ViewerDoc) => void;
}

export default function EmailTraceResponse({ docs, onDocClick }: Props) {
  if (!docs.length) return null;

  return (
    <div className="mt-3 space-y-2">
      {docs.map((d, i) => (
        <button
          key={`${d.doc_id}_${i}`}
          onClick={() =>
            onDocClick({ docId: d.doc_id, fileName: d.doc_name })
          }
          className="w-full text-left p-3 rounded-lg border border-[var(--border)] hover:border-[var(--accent)] bg-[var(--bg-surface)] transition-colors"
        >
          <div className="flex items-center gap-2 text-xs text-[var(--text-secondary)]">
            <span>{d.date || '—'}</span>
            <span className="text-[var(--accent)]">&#8594;</span>
          </div>
          <p className="text-sm text-[var(--text-primary)] mt-1">
            {d.reason || d.doc_name}
          </p>
          <p className="text-xs text-[var(--text-secondary)] mt-0.5">
            {d.doc_name}
          </p>
        </button>
      ))}
    </div>
  );
}
