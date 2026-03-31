import type { DocContent } from '../../types/api';

interface Props {
  content: DocContent;
}

export default function ExcelPreview({ content }: Props) {
  if (!content.rows.length) {
    return (
      <div className="p-4 text-sm text-[var(--text-secondary)]">
        No data available
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-auto p-2">
      <p className="text-xs text-[var(--text-secondary)] mb-2">
        {content.file_name} ({content.total_rows} rows)
      </p>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-[var(--border)]">
            {content.columns.map((col) => (
              <th
                key={col}
                className="text-left px-2 py-1 text-[var(--text-secondary)] font-medium sticky top-0 bg-[var(--bg-surface)]"
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
              className="border-b border-[var(--border)] last:border-0"
            >
              {content.columns.map((col) => (
                <td
                  key={col}
                  className="px-2 py-1 text-[var(--text-primary)]"
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
