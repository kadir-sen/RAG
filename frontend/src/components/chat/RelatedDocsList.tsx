import type { RelatedDoc } from '../../types/api';
import type { ViewerDoc } from '../../stores/uiStore';
import Badge from '../shared/Badge';

interface Props {
  docs: RelatedDoc[];
  onDocClick: (doc: ViewerDoc) => void;
}

export default function RelatedDocsList({ docs, onDocClick }: Props) {
  if (!docs.length) return null;

  // Sort chronologically by date
  const sorted = [...docs].sort((a, b) => (a.date || '').localeCompare(b.date || ''));

  return (
    <div className="mt-3">
      <p className="text-xs text-[var(--text-secondary)] mb-1.5 font-medium">
        Related Documents ({sorted.length})
      </p>
      <div className="rounded-lg border border-[var(--border)] overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-[var(--bg-surface)]">
              <th className="text-left px-3 py-1.5 text-[10px] text-[var(--text-muted)] font-medium uppercase">
                Date
              </th>
              <th className="text-left px-3 py-1.5 text-[10px] text-[var(--text-muted)] font-medium uppercase">
                Document
              </th>
              <th className="text-left px-3 py-1.5 text-[10px] text-[var(--text-muted)] font-medium uppercase">
                Type
              </th>
              <th className="px-3 py-1.5 w-16"></th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((d, i) => (
              <tr
                key={`${d.doc_id}_${i}`}
                className="border-t border-[var(--border)] hover:bg-[var(--bg-hover)] transition-colors"
              >
                <td className="px-3 py-2 text-xs text-[var(--text-secondary)] whitespace-nowrap">
                  {d.date || '\u2014'}
                </td>
                <td className="px-3 py-2 text-xs text-[var(--text-primary)] truncate max-w-[200px]">
                  {d.doc_name}
                  {d.sender && (
                    <span className="block text-[10px] text-[var(--text-muted)]">
                      {d.sender} {d.recipient ? `\u2192 ${d.recipient}` : ''}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2">
                  {d.doc_type && <Badge label={d.doc_type} />}
                </td>
                <td className="px-3 py-2">
                  <button
                    onClick={() => d.doc_id && onDocClick({ docId: d.doc_id, fileName: d.doc_name })}
                    disabled={!d.doc_id}
                    className={`px-2.5 py-1 rounded text-[10px] font-medium transition-colors ${
                      d.doc_id
                        ? 'bg-[var(--accent)] text-[var(--bg-primary)] hover:bg-[var(--accent-hover)] cursor-pointer'
                        : 'bg-[var(--bg-surface)] text-[var(--text-muted)] cursor-not-allowed opacity-50'
                    }`}
                  >
                    View
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
