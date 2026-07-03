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

function BouncingDots() {
  return (
    <span className="inline-flex gap-1" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-1.5 h-1.5 rounded-full bg-[var(--accent)] animate-bounce"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </span>
  );
}

interface Props {
  requestId: string | null;
  visible: boolean;
}

/**
 * Live activity feed shown in place of the static "Analyzing…" spinner while a
 * query runs. Steps stream in via polling; the latest is "active" (accent +
 * bouncing dots), earlier ones settle to muted with a check. Falls back to the
 * plain typing dots until the first step arrives.
 */
export default function ActivityFeed({ requestId, visible }: Props) {
  const { steps } = useActivityFeed(requestId, visible);
  if (!visible) return null;

  if (!steps.length) {
    return (
      <div className="flex items-center gap-2 px-4 py-3" role="status" aria-label="Working">
        <BouncingDots />
        <span className="text-sm text-[var(--text-secondary)]">thinking…</span>
      </div>
    );
  }

  const last = steps.length - 1;
  return (
    <div
      className="px-4 py-3"
      role="status"
      aria-live="polite"
      aria-label="Assistant activity"
    >
      <ul className="flex flex-col gap-1.5">
        {steps.map((s: ActivityStep, i: number) => {
          const active = i === last;
          return (
            <li
              key={s.seq}
              className={`flex items-center gap-2 text-[13px] transition-colors ${
                active ? 'text-[var(--text-primary)]' : 'text-[var(--text-muted)]'
              }`}
            >
              <span
                className={`font-mono text-[11px] w-3 text-center ${
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
              {active && <span className="ml-1"><BouncingDots /></span>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
