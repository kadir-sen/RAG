import type { RelatedDoc } from '../../types/api';
import type { ViewerDoc } from '../../stores/uiStore';
import FileTypeBadge from '../ui/FileTypeBadge';
import { formatTimelineLabel } from '../../utils/timeline';

interface Props {
  docs: RelatedDoc[];
  onDocClick: (doc: ViewerDoc) => void;
}

// Normal chat surfaces related documents as a soft strip of clickable bubbles
// under the human answer — not a table. Document-analysis mode still gets the
// chronological table (handled upstream in AssistantMessage).
export default function RelatedDocsList({ docs, onDocClick }: Props) {
  if (!docs.length) return null;

  // Sort chronologically by date (undated last).
  const sorted = [...docs].sort((a, b) => (a.date || '9999').localeCompare(b.date || '9999'));

  return (
    <div className="mt-3">
      <p className="text-xs text-[var(--text-secondary)] mb-2 font-medium">
        Related Documents ({sorted.length})
      </p>
      <div className="flex flex-wrap gap-2">
        {sorted.map((d, i) => {
          const ext = d.doc_name.toLowerCase().match(/\.([a-z0-9]+)$/)?.[1];
          const dateLabel = formatTimelineLabel(d.date);
          return (
            <button
              key={`${d.doc_id}_${i}`}
              onClick={() => d.doc_id && onDocClick({ docId: d.doc_id, fileName: d.doc_name })}
              disabled={!d.doc_id}
              title={d.doc_name}
              className={`group inline-flex items-center gap-2 max-w-full pl-1.5 pr-3 py-1.5 rounded-[2px] border transition-colors text-left ${
                d.doc_id
                  ? 'border-[var(--border)] bg-[var(--bg-surface)] hover:border-[var(--accent)] hover:bg-[var(--bg-hover)] cursor-pointer'
                  : 'border-[var(--border)] bg-[var(--bg-surface)] opacity-50 cursor-not-allowed'
              }`}
            >
              <FileTypeBadge fileType={d.doc_type} extension={ext} size="sm" />
              <span className="min-w-0 truncate text-xs text-[var(--text-primary)]">
                {d.doc_name}
              </span>
              {dateLabel !== '—' && (
                <span className="shrink-0 text-[10px] font-mono text-[var(--text-muted)]">
                  {dateLabel}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
