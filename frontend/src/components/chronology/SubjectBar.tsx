import { useRef, useState } from 'react';
import type { ChronologySubject } from '../../api/chronologyApi';

/**
 * Type a subject, get that issue's chronology.
 *
 * You are not expected to know the title — "the procurement risk transfer" and
 * "wiesbaden" both resolve to the contract-strategy chronology. Matching is
 * server-side, deterministic and cheap, so the composer behaves like a lookup
 * rather than a conversation: no transcript, no waiting on a model.
 *
 * When the subject is ambiguous or matches nothing the bar says so and offers
 * the candidates as chips. Handing over the chronology for the wrong issue is
 * a real problem, so asking beats guessing.
 */
interface Props {
  onSubmit: (subject: string) => void;
  onPick: (ref: string) => void;
  status: 'idle' | 'loading' | 'match' | 'ambiguous' | 'none';
  candidates: ChronologySubject[];
  lastSubject: string;
}

export default function SubjectBar({
  onSubmit,
  onPick,
  status,
  candidates,
  lastSubject,
}: Props) {
  const [value, setValue] = useState('');
  const ref = useRef<HTMLInputElement>(null);

  const send = () => {
    const s = value.trim();
    if (!s || status === 'loading') return;
    onSubmit(s);
  };

  const message =
    status === 'ambiguous'
      ? `"${lastSubject}" could be more than one of these. Which did you mean?`
      : status === 'none'
        ? `Nothing matches "${lastSubject}" closely enough to pick for you. Here is everything on file.`
        : null;

  return (
    <div className="border-b border-[var(--border)] bg-[var(--bg-secondary)] px-4 md:px-8 py-3">
      <div className="max-w-4xl mx-auto">
        <label
          htmlFor="chron-subject"
          className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-muted)]"
        >
          Chronology subject
        </label>
        <div className="mt-1.5 flex items-center gap-2">
          <input
            id="chron-subject"
            ref={ref}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                send();
              }
            }}
            placeholder="Describe the subject — “the utility diversions”, “flawed contract strategy”…"
            disabled={status === 'loading'}
            className="flex-1 px-3 py-2 rounded-[2px] bg-[var(--bg-input)] border border-[var(--border)] focus:border-[var(--ink)] text-[13px] text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none disabled:opacity-60 transition-colors"
          />
          <button
            type="button"
            onClick={send}
            disabled={!value.trim() || status === 'loading'}
            className="shrink-0 px-3.5 py-2 rounded-[2px] bg-[var(--accent)] text-[var(--accent-ink)] font-mono text-[10px] tracking-[0.18em] uppercase disabled:bg-[var(--wash-firm)] disabled:text-[var(--text-muted)] transition-colors"
          >
            {status === 'loading' ? 'Finding…' : 'Build'}
          </button>
        </div>

        {message && (
          <div role="status" className="mt-2.5">
            <p className="text-[12px] text-[var(--text-secondary)]">{message}</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {candidates.map((c) => (
                <button
                  key={c.ref}
                  type="button"
                  onClick={() => onPick(c.ref)}
                  title={c.summary}
                  className="px-2 py-1 rounded-[2px] border border-[var(--border)] hover:border-[var(--ink)] bg-[var(--wash)] font-mono text-[10px] text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
                >
                  {c.ref} · {c.title}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
