import MonoTag from '../ui/MonoTag';
import type { TimelineEvent } from '../../utils/timeline';

interface Props {
  events: TimelineEvent[];
  topic?: string;
  onEventClick?: (event: TimelineEvent) => void;
  caption?: string;
  className?: string;
}

// Chronological, clickable table view of the documents related to a topic.
// Shares the same TimelineEvent shape (and `mapRelatedDocsToTimeline` mapping)
// as the timeline view, so dates are pre-sorted and badges are resolved — this
// component only owns the table layout. Each row opens the document.
export default function DocumentAnalysisTable({
  events,
  topic,
  onEventClick,
  caption,
  className = '',
}: Props) {
  if (events.length === 0) {
    return (
      <div className={`rounded-md border border-[var(--border)] bg-[var(--wash)] px-4 py-8 text-center ${className}`}>
        <p className="font-mono text-[11px] text-[var(--text-muted)]">
          No documents found{topic ? ` for "${topic}"` : ''}.
        </p>
      </div>
    );
  }

  const clickable = Boolean(onEventClick);

  return (
    <div className={`flex flex-col gap-3 ${className}`}>
      <div className="flex flex-wrap gap-2 items-center">
        <MonoTag tone="accent">● {events.length} document{events.length === 1 ? '' : 's'}</MonoTag>
        {topic && <MonoTag>topic · {topic}</MonoTag>}
      </div>

      <div className="rounded-md border border-[var(--border)] bg-[var(--wash)] overflow-hidden">
        <div className="flex items-center justify-between px-4 py-2 border-b border-dashed border-[var(--border)]">
          <span className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-secondary)]">
            {caption ?? 'Chronological roadmap'}
          </span>
          <span className="font-mono text-[10px] text-[var(--text-muted)]">oldest → newest</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b border-[var(--border)]">
                {['Date', 'Document', 'Type', 'People / Reason', ''].map((h, i) => (
                  <th
                    key={h || `col-${i}`}
                    className="text-left px-3 py-2 font-mono text-[10px] tracking-[0.12em] uppercase text-[var(--text-muted)] font-medium whitespace-nowrap"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {events.map((e, i) => {
                const dot = e.badge.dot;
                return (
                  <tr
                    key={e.id ?? `${e.date}-${i}`}
                    onClick={() => clickable && e.id && onEventClick?.(e)}
                    className={`border-t border-[var(--border)]/60 transition-colors ${
                      clickable ? 'cursor-pointer hover:bg-[rgba(var(--accent-rgb),0.06)]' : ''
                    }`}
                    style={e.highlight ? { background: 'rgba(var(--accent-rgb), 0.06)' } : undefined}
                  >
                    <td className="px-3 py-2.5 align-top font-mono text-[11px] text-[var(--text-secondary)] whitespace-nowrap">
                      {e.label}
                    </td>
                    <td className="px-3 py-2.5 align-top">
                      <div className="flex items-center gap-2 flex-wrap">
                        {e.tag && (
                          <span
                            className="font-mono text-[9px] tracking-wider px-1.5 py-0.5 border rounded"
                            style={{ color: dot, borderColor: dot }}
                          >
                            {e.tag}
                          </span>
                        )}
                        <span className="text-[13px] font-semibold text-[var(--text-primary)] break-words">
                          {e.title}
                        </span>
                      </div>
                    </td>
                    <td className="px-3 py-2.5 align-top whitespace-nowrap">
                      <span
                        className="inline-flex items-center gap-1.5 font-mono text-[10px] tracking-wider"
                        style={{ color: dot }}
                      >
                        <span aria-hidden="true" className="w-1.5 h-1.5" style={{ background: dot }} />
                        {e.type}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 align-top max-w-[280px]">
                      {e.who && (
                        <p className="font-mono text-[10px] text-[var(--text-secondary)]">{e.who}</p>
                      )}
                      {e.note && (
                        <p className="text-[12px] text-[var(--text-secondary)] mt-0.5 leading-snug">
                          {e.note}
                        </p>
                      )}
                      {!e.who && !e.note && (
                        <span className="text-[var(--text-muted)]">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 align-top text-right whitespace-nowrap">
                      {clickable && e.id && (
                        <span className="font-mono text-[10px] text-[var(--accent)]">open →</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
