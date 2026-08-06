import { useState } from 'react';
import type { DocContent } from '../../types/api';

interface Props {
  content: DocContent;
}

// Collapsible schema panel — learned column meanings (jargon) + types, so the
// viewer explains what each column is before showing the rows.
function SchemaPanel({ content }: { content: DocContent }) {
  const [open, setOpen] = useState(false);
  const cols = content.schema_columns ?? [];
  if (!cols.length) return null;
  const withMeaning = cols.filter((c) => c.meaning).length;
  return (
    <div className="border-b border-[var(--border)] bg-[var(--bg-surface)]">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-3 py-2 text-[11px] font-mono text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
      >
        <span>
          {open ? '▾' : '▸'} Schema · {cols.length} columns
          {withMeaning ? ` · ${withMeaning} with meaning` : ''}
          {content.row_from ? ` · rows ${content.row_from}–${content.row_to ?? content.row_from}` : ''}
        </span>
        {content.sheet_name ? <span className="opacity-70">sheet: {content.sheet_name}</span> : null}
      </button>
      {open && (
        <div className="px-3 pb-3">
          {content.description ? (
            <p className="mb-2 text-[11px] text-[var(--text-muted)]">{content.description}</p>
          ) : null}
          <table className="min-w-max font-mono text-[11px] border-collapse">
            <thead>
              <tr className="text-left text-[var(--text-muted)]">
                <th className="px-2 py-1 font-semibold">Column</th>
                <th className="px-2 py-1 font-semibold">Type</th>
                <th className="px-2 py-1 font-semibold">Meaning</th>
              </tr>
            </thead>
            <tbody>
              {cols.map((c) => (
                <tr key={c.name} className="border-t border-[var(--border)]/50">
                  <td className="px-2 py-1 text-[var(--text-primary)] whitespace-nowrap">{c.name}</td>
                  <td className="px-2 py-1 text-[var(--text-secondary)] whitespace-nowrap">{c.dtype}</td>
                  <td className="px-2 py-1 text-[var(--text-muted)]">{c.meaning || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// Mono engineering table — wireframes ViewerExcel: dense rows, zebra striping,
// border-bottom dashed dividers, sticky header, horizontal scroll for wide
// data. Filename + row/col counts are shown in the toolbar's chip bar.
export default function ExcelPreview({ content }: Props) {
  if (!content.rows.length) {
    return (
      <div data-testid="document-table-scroll" className="min-w-0 flex-1 overflow-auto overscroll-contain">
        <SchemaPanel content={content} />
        <div className="p-6 text-center text-sm text-[var(--text-secondary)] font-mono">
          No data available
        </div>
      </div>
    );
  }

  const columns = content.columns?.length
    ? content.columns
    : Object.keys(content.rows[0] as Record<string, unknown>);

  return (
    <div data-testid="document-table-scroll" className="min-w-0 flex-1 overflow-auto overscroll-contain">
      <SchemaPanel content={content} />
      <table className="min-w-max font-mono text-[11px] tabular-nums border-collapse">
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col}
                scope="col"
                className={`text-left px-3 py-2 font-semibold text-[var(--text-primary)] bg-[var(--bg-surface)] border-b-2 border-r border-[var(--border)] last:border-r-0 sticky top-0 whitespace-nowrap min-w-[72px] ${columns[0] === col ? 'left-0 z-20' : 'z-10'}`}
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
                  ? 'bg-[var(--wash)]'
                  : 'bg-transparent'
              }
            >
              {columns.map((col) => (
                <td
                  key={col}
                  className={`px-3 py-1.5 text-[var(--text-secondary)] border-b border-dashed border-[var(--border)]/60 border-r border-r-[var(--border)]/40 last:border-r-0 whitespace-nowrap min-w-[72px] ${columns[0] === col ? `${i % 2 ? 'bg-[var(--wash)]' : 'bg-[var(--bg-secondary)]'} sticky left-0 z-10` : ''}`}
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
