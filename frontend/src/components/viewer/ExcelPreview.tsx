import type { DocContent } from '../../types/api';

interface Props {
  content: DocContent;
}

// Mono engineering table — wireframes ViewerExcel: dense rows, zebra striping,
// border-bottom dashed dividers, sticky header, horizontal scroll for wide
// data. Filename + row/col counts are shown in the toolbar's chip bar.
export default function ExcelPreview({ content }: Props) {
  if (!content.rows.length) {
    return (
      <div className="p-6 text-center text-sm text-[var(--text-secondary)] font-mono">
        No data available
      </div>
    );
  }

  const columns = content.columns?.length
    ? content.columns
    : Object.keys(content.rows[0] as Record<string, unknown>);

  return (
    <div className="flex-1 overflow-auto">
      <table className="min-w-full font-mono text-[11px] tabular-nums border-collapse">
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col}
                scope="col"
                className="text-left px-3 py-2 font-semibold text-[var(--text-primary)] bg-[var(--bg-surface)] border-b-2 border-r border-[var(--border)] last:border-r-0 sticky top-0 whitespace-nowrap min-w-[72px]"
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {content.rows.map((row, i) => (
            <tr
              key={i}
              className={
                i % 2
                  ? 'bg-[rgba(255,255,255,0.02)]'
                  : 'bg-transparent'
              }
            >
              {columns.map((col) => (
                <td
                  key={col}
                  className="px-3 py-1.5 text-[var(--text-secondary)] border-b border-dashed border-[var(--border)]/60 border-r border-r-[var(--border)]/40 last:border-r-0 whitespace-nowrap min-w-[72px]"
                >
                  {String((row as Record<string, unknown>)[col] ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
