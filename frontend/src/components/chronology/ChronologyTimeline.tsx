import type { ReactNode } from 'react';
import MonoTag from '../ui/MonoTag';
import FileTypeBadge from '../ui/FileTypeBadge';
import TimelineNode from './TimelineNode';
import type { TimelineEvent } from '../../utils/timeline';

export type { TimelineEvent } from '../../utils/timeline';
export { mapRelatedDocsToTimeline, formatTimelineLabel } from '../../utils/timeline';

interface Props {
  events: TimelineEvent[];
  topic?: string;
  // Optional overrides for chrome (intro vs response):
  emptyState?: ReactNode;
  showFilters?: boolean;
  onEventClick?: (event: TimelineEvent) => void;
  className?: string;
  caption?: string;
}

export default function ChronologyTimeline({
  events,
  topic,
  emptyState,
  showFilters = true,
  onEventClick,
  className = '',
  caption,
}: Props) {
  if (events.length === 0) {
    return (
      <div className={`rounded-md border border-[var(--border)] bg-[var(--wash)] px-4 py-8 text-center ${className}`}>
        {emptyState ?? (
          <p className="font-mono text-[11px] text-[var(--text-muted)]">
            No documents found{topic ? ` for "${topic}"` : ''}.
          </p>
        )}
      </div>
    );
  }

  // Per-type counts for the filter chip row.
  const counts = events.reduce<Record<string, number>>((acc, e) => {
    acc[e.type] = (acc[e.type] ?? 0) + 1;
    return acc;
  }, {});
  const distinctTypes = Object.keys(counts);

  return (
    <div className={`flex flex-col gap-3 ${className}`}>
      {showFilters && (
        <div className="flex flex-wrap gap-2 items-center">
          <MonoTag tone="accent">● ALL · {events.length}</MonoTag>
          {distinctTypes.map((t) => {
            const sample = events.find((e) => e.type === t);
            const dot = sample?.badge.dot ?? 'var(--text-muted)';
            return (
              <MonoTag key={t}>
                <span aria-hidden="true" className="w-1.5 h-1.5" style={{ background: dot }} />
                {t} · {counts[t]}
              </MonoTag>
            );
          })}
        </div>
      )}

      <div className="rounded-md border border-[var(--border)] bg-[var(--wash)] overflow-hidden">
        <div className="flex items-center justify-between px-4 py-2 border-b border-dashed border-[var(--border)]">
          <span className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-secondary)]">
            {caption ?? 'Chronological roadmap'}
          </span>
          <span className="font-mono text-[10px] text-[var(--text-muted)]">oldest → newest</span>
        </div>

        <ol className="px-4 md:px-6 py-5 flex flex-col gap-4">
          {events.map((e, i) => {
            const isLast = i === events.length - 1;
            const dot = e.badge.dot;
            const clickable = Boolean(onEventClick);
            return (
              <li
                key={e.id ?? `${e.date}-${i}`}
                className="grid grid-cols-[7rem_24px_1fr_auto] items-start gap-3"
              >
                {/* Left-aligned and wider than it was: the store's dates are
                    free-form ("1970 to 1975"), so they neither fit a 64px
                    column nor line up usefully when right-aligned. */}
                <span className="font-mono text-[11px] text-[var(--text-secondary)] pt-2 leading-snug">
                  {e.label}
                </span>

                <TimelineNode type={e.type} color={dot} highlight={e.highlight} showRailBelow={!isLast} />

                <button
                  type="button"
                  disabled={!clickable}
                  onClick={() => onEventClick?.(e)}
                  className="text-left rounded-md border bg-[var(--wash)] hover:bg-[rgba(var(--accent-rgb),0.06)] transition-colors px-3 py-2.5 disabled:cursor-default disabled:hover:bg-[var(--wash)]"
                  style={{
                    borderColor: e.highlight ? 'var(--accent)' : 'var(--border)',
                    background: e.highlight ? 'rgba(var(--accent-rgb), 0.08)' : undefined,
                  }}
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    {e.tag && (
                      <span
                        className="font-mono text-[9px] tracking-wider px-1.5 py-0.5 border rounded"
                        style={{ color: dot, borderColor: dot }}
                      >
                        {e.tag}
                      </span>
                    )}
                    <span className="text-[13px] md:text-sm font-semibold text-[var(--text-primary)]">
                      {e.title}
                    </span>
                  </div>
                  {e.who && (
                    <p className="font-mono text-[10px] text-[var(--text-secondary)] mt-1">
                      {e.who}
                    </p>
                  )}
                  {e.note && (
                    <p className="text-[12px] text-[var(--text-secondary)] mt-1 leading-snug">
                      {e.note}
                    </p>
                  )}
                </button>

                {/* The source document, so a row says which paper it came
                    from without opening it. Full name in the title attribute
                    because these are long and the column is not. */}
                <span className="pt-3 flex flex-col items-end gap-0.5 max-w-[11rem]">
                  {e.source && (
                    <span
                      className="flex items-center gap-1.5 min-w-0 w-full justify-end"
                      title={e.source}
                    >
                      <FileTypeBadge extension={e.source.slice(e.source.lastIndexOf('.'))} size="sm" />
                      <span className="font-mono text-[10px] text-[var(--text-muted)] truncate">
                        {e.source}
                      </span>
                    </span>
                  )}
                  {clickable && (
                    <span className="font-mono text-[10px] text-[var(--accent)]">open →</span>
                  )}
                </span>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}

