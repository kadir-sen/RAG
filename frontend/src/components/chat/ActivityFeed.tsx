import { useActivityFeed } from '../../hooks/useActivityFeed';
import type { ActivityStep } from '../../types/api';

// Small monospace glyph per step kind so the feed reads like a build log.
const KIND_GLYPH: Record<string, string> = {
  thinking: '◇',
  routing: '→',
  searching: '⚲',
  reading: '▤',
  related: '◈',
  analysing: '∴',
  tool: '⚙',
  answer: '✓',
};

function glyph(kind: string): string {
  return KIND_GLYPH[kind] ?? '·';
}

/* Square pips, not circles — the sheet has no round corners anywhere else. */
function BouncingDots() {
  return (
    <span className="inline-flex gap-1" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-1 h-1 bg-[var(--accent)] animate-bounce"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </span>
  );
}

interface Props {
  requestId?: string | null;
  visible: boolean;
  /** Pre-supplied steps, which switch the component out of polling. The
      chronology build hands them in already paced (see usePacedSteps) — the feed
      is otherwise identical, so it renders them rather than owning a second
      copy of this layout. */
  steps?: ActivityStep[];
}

/**
 * Live activity feed shown in place of the static "Analyzing…" spinner while a
 * query runs. Steps stream in via polling; the latest is "active" (accent +
 * bouncing dots), earlier ones settle to muted with a check. Falls back to the
 * plain typing dots until the first step arrives.
 */
export default function ActivityFeed({ requestId, visible, steps: given }: Props) {
  const polled = useActivityFeed(requestId ?? null, visible && given === undefined);
  const steps = given ?? polled.steps;
  if (!visible) return null;

  if (!steps.length) {
    return (
      <div className="px-2 md:px-6 py-3" role="status" aria-label="Working">
        <div className="max-w-3xl flex items-center gap-2 pl-3 border-l border-[var(--border)]">
          <span className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-muted)]">
            working
          </span>
          <BouncingDots />
        </div>
      </div>
    );
  }

  const last = steps.length - 1;
  return (
    <div
      className="px-2 md:px-6 py-3"
      role="status"
      aria-live="polite"
      aria-label="Assistant activity"
    >
      {/* A revision column: hairline rule down the left, sequence numbers in
          mono against it. The running step is struck in to full ink; settled
          ones fall back to annotation grey with a check. */}
      <ol className="max-w-3xl flex flex-col border-l border-[var(--border)]">
        {steps.map((s: ActivityStep, i: number) => {
          const active = i === last;
          return (
            <li
              key={s.seq}
              className={`flex items-baseline gap-2.5 pl-3 py-[3px] text-[13px] transition-colors ${
                active
                  ? 'text-[var(--text-primary)] border-l border-[var(--ink)] -ml-px'
                  : 'text-[var(--text-muted)]'
              }`}
            >
              <span
                className="font-mono text-[10px] tabular-nums text-[var(--text-muted)] w-4 shrink-0"
                aria-hidden="true"
              >
                {String(i + 1).padStart(2, '0')}
              </span>
              <span
                className={`font-mono text-[11px] w-3 shrink-0 text-center ${
                  active ? 'text-[var(--accent)]' : 'text-[var(--text-muted)]'
                }`}
                aria-hidden="true"
              >
                {active ? glyph(s.kind) : '✓'}
              </span>
              <span className="truncate">{s.label}</span>
              {s.detail && (
                <span className="font-mono text-[10px] text-[var(--text-muted)] truncate">
                  {s.detail}
                </span>
              )}
              {active && <span className="ml-1 self-center"><BouncingDots /></span>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
