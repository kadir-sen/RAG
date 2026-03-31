import type { RelatedDoc } from '../../types/api';
import type { ViewerDoc } from '../../stores/uiStore';
import Badge from '../shared/Badge';

interface Props {
  docs: RelatedDoc[];
  onDocClick: (doc: ViewerDoc) => void;
}

export default function DocListResponse({ docs, onDocClick }: Props) {
  if (!docs.length) return null;

  const hasSenderInfo = docs.some(d => d.sender || d.recipient);

  return (
    <div className="mt-3 rounded-lg border border-[var(--border)] overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-[var(--bg-surface)]">
              <th className="text-left px-3 py-2 text-xs text-[var(--text-secondary)] font-medium">
                Date
              </th>
              <th className="text-left px-3 py-2 text-xs text-[var(--text-secondary)] font-medium">
                Document
              </th>
              {hasSenderInfo && (
                <>
                  <th className="text-left px-3 py-2 text-xs text-[var(--text-secondary)] font-medium">
                    From
                  </th>
                  <th className="text-left px-3 py-2 text-xs text-[var(--text-secondary)] font-medium">
                    To
                  </th>
                </>
              )}
              <th className="text-left px-3 py-2 text-xs text-[var(--text-secondary)] font-medium">
                Type
              </th>
              <th className="px-3 py-2 w-16"></th>
            </tr>
          </thead>
          <tbody>
            {docs.map((d, i) => (
              <tr
                key={`${d.doc_id}_${i}`}
                className="border-t border-[var(--border)] hover:bg-[var(--bg-hover)] transition-colors"
              >
                <td className="px-3 py-2 text-[var(--text-secondary)] whitespace-nowrap">
                  {d.date || '\u2014'}
                </td>
                <td className="px-3 py-2 text-[var(--text-primary)]">
                  {d.doc_name}
                </td>
                {hasSenderInfo && (
                  <>
                    <td className="px-3 py-2 text-[var(--text-secondary)] truncate max-w-[150px]">
                      {d.sender || '\u2014'}
                    </td>
                    <td className="px-3 py-2 text-[var(--text-secondary)] truncate max-w-[150px]">
                      {d.recipient || '\u2014'}
                    </td>
                  </>
                )}
                <td className="px-3 py-2">
                  <Badge label={d.doc_type || 'doc'} />
                </td>
                <td className="px-3 py-2">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDocClick({ docId: d.doc_id, fileName: d.doc_name });
                    }}
                    className="px-2.5 py-1 rounded text-[10px] font-medium bg-[var(--accent)] text-[var(--bg-primary)] hover:bg-[var(--accent-hover)] transition-colors"
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
