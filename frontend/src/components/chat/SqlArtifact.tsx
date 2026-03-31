import { useState } from 'react';
import type { SQLArtifact as SQLArtifactType } from '../../types/api';
import type { ViewerDoc } from '../../stores/uiStore';

interface Props {
  artifact: SQLArtifactType;
  onSourceClick?: (doc: ViewerDoc) => void;
}

export default function SqlArtifact({ artifact, onSourceClick }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <div className="mt-3 rounded-lg border border-[var(--border)] overflow-hidden">
      {/* Source file link */}
      {artifact.source_file_name && onSourceClick && (
        <button
          onClick={() => onSourceClick({
            docId: artifact.source_file_id,
            fileName: artifact.source_file_name,
          })}
          className="w-full flex items-center gap-2 px-3 py-2 bg-[var(--accent)]/10 border-b border-[var(--accent)]/20 text-sm text-[var(--accent)] hover:bg-[var(--accent)]/20 transition-colors text-left cursor-pointer"
        >
          <span className="w-2 h-2 rounded-full bg-[var(--accent)] flex-shrink-0 animate-pulse" />
          <span className="underline decoration-dotted underline-offset-2">Source: {artifact.source_file_name}</span>
          <span className="text-[10px] ml-auto opacity-60">Click to view</span>
        </button>
      )}

      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-3 py-2 bg-[var(--bg-surface)] hover:bg-[var(--bg-hover)] transition-colors text-sm"
      >
        <span className="text-[var(--text-secondary)]">
          Show details
          {artifact.tables_used.length > 0 &&
            ` (${artifact.tables_used.join(', ')})`}
        </span>
        <span className="text-[var(--text-secondary)]">
          {open ? '▲' : '▼'}
        </span>
      </button>

      {open && (
        <div className="p-3 space-y-3">
          {/* SQL */}
          <div>
            <p className="text-xs text-[var(--text-secondary)] mb-1">SQL</p>
            <pre className="p-2 rounded bg-[var(--bg-secondary)] text-xs text-green-400 overflow-x-auto">
              {artifact.generated_sql}
            </pre>
          </div>

          {/* Preview table */}
          {artifact.preview_rows.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-1">
                <p className="text-xs text-[var(--text-secondary)]">
                  Result ({artifact.row_count} rows)
                </p>
                <button
                  onClick={() => {
                    const rows = artifact.preview_rows;
                    if (!rows.length) return;
                    const cols = Object.keys(rows[0]);
                    const csv = [cols.join(','), ...rows.map(r => cols.map(c => {
                      const v = String(r[c] ?? '');
                      return v.includes(',') ? `"${v}"` : v;
                    }).join(','))].join('\n');
                    const blob = new Blob([csv], { type: 'text/csv' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `query_result_${Date.now()}.csv`;
                    a.click();
                    URL.revokeObjectURL(url);
                  }}
                  className="text-[10px] px-2 py-0.5 rounded bg-[var(--accent)]/20 text-[var(--accent)] hover:bg-[var(--accent)]/30 transition-colors"
                >
                  Download CSV
                </button>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-[var(--border)]">
                      {Object.keys(artifact.preview_rows[0]).map((col) => (
                        <th
                          key={col}
                          className="text-left px-2 py-1 text-[var(--text-secondary)] font-medium"
                        >
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {artifact.preview_rows.map((row, i) => (
                      <tr
                        key={i}
                        className="border-b border-[var(--border)] last:border-0"
                      >
                        {Object.values(row).map((val, j) => (
                          <td
                            key={j}
                            className="px-2 py-1 text-[var(--text-primary)]"
                          >
                            {String(val ?? '')}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
