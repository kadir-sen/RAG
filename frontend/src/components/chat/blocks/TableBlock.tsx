import type { DataTableBlock } from '../../../types/api';

/** Structured table block — same visual language as ProgrammeResult tables. */
export default function TableBlock({ block }: { block: DataTableBlock }) {
  return (
    <div className="my-3">
      {block.title && (
        <p className="text-[11px] font-medium text-[var(--text-secondary)] mb-1">
          {block.title}
        </p>
      )}
      <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
        <table className="w-full text-xs">
          <thead className="bg-[var(--bg-primary)]">
            <tr>
              {block.columns.map((c) => (
                <th key={c}
                    className="px-3 py-2 text-left text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wider border-b border-[var(--border)]">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row, i) => (
              <tr key={i}
                  className="even:bg-[var(--bg-primary)]/30 hover:bg-[var(--bg-hover)] transition-colors">
                {row.map((cell, j) => (
                  <td key={j}
                      className="px-3 py-1.5 text-[var(--text-primary)] border-b border-[var(--border)]/50 whitespace-nowrap">
                    {cell ?? '—'}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {block.caption && (
        <p className="mt-1 text-[10px] text-[var(--text-muted)]">{block.caption}</p>
      )}
    </div>
  );
}
