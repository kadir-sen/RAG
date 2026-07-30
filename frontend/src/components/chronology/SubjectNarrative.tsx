import type { ChronologyEntry, ChronologySubject } from '../../api/chronologyApi';
import { downloadSubjectDocx } from '../../api/chronologyApi';
import DownloadDocxButton from './DownloadDocxButton';

/**
 * An authored chronology, told in full.
 *
 * The source is a numbered narrative ("6.4.1 The strategy for delivering…"),
 * so it is drawn as one: the reference in mono against a hairline rule, the
 * paragraph beside it, sub-points indented under their entry. Same revision
 * column as the activity feed and the step trail — a numbered sequence with a
 * rule down its left is the sheet's way of saying "these happened in order".
 */
interface Props {
  subject: ChronologySubject;
  entries: ChronologyEntry[];
  onClear: () => void;
  /** Re-run the evidence pass. A second look at the same subject reuses what was
      already resolved, which is right — but when the corpus has changed you want
      the full pass, and dressing a cache hit as a fresh analysis would be the
      misrepresentation this whole area avoids. */
  onRebuild?: () => void;
}

export default function SubjectNarrative({ subject, entries, onClear, onRebuild }: Props) {
  return (
    <article className="mt-5">
      <header className="pb-3 border-b border-[var(--border)]">
        <div className="flex items-baseline justify-between gap-4">
          <p className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-muted)]">
            Chronology · {subject.ref}
          </p>
          <div className="shrink-0 flex items-baseline gap-4">
            <DownloadDocxButton onDownload={() => downloadSubjectDocx(subject.ref)} />
            {onRebuild && (
              <button
                type="button"
                onClick={onRebuild}
                className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
              >
                rebuild
              </button>
            )}
            {/* Without this the narrative is a one-way door — there is no other
                way back to the events the corpus produced. */}
            <button
              type="button"
              onClick={onClear}
              className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
            >
              ← all events
            </button>
          </div>
        </div>
        <h2 className="mt-1.5 text-[17px] font-semibold tracking-tight text-[var(--text-primary)]">
          {subject.title}
        </h2>
        <p className="mt-1.5 text-[12px] text-[var(--text-secondary)] max-w-2xl">
          {subject.summary}
        </p>
      </header>

      {entries.length === 0 ? (
        <p className="mt-4 text-[12px] text-[var(--text-muted)]">
          This chronology has no readable entries — the source document may be
          missing from content/chronologies/.
        </p>
      ) : (
        <ol className="mt-4">
          {entries.map((e) => (
            <li
              key={e.ref}
              className="grid grid-cols-[7.5rem_1fr] gap-x-4 py-3 border-b border-[var(--border)] last:border-b-0"
            >
              {/* The date column is what makes this read as a chronology
                  rather than a list: when, then what happened. Entries that
                  open with context instead of a date show their reference
                  there, so the column is never empty. */}
              <div className="pt-0.5">
                <p className="font-mono text-[11px] tabular-nums text-[var(--text-primary)] leading-5">
                  {e.date || '—'}
                </p>
                <p className="font-mono text-[9px] tabular-nums tracking-[0.1em] text-[var(--text-muted)] mt-0.5">
                  {e.ref}
                </p>
              </div>

              <div className="min-w-0">
                <p className="text-[13px] leading-6 text-[var(--text-primary)]">{e.text}</p>
                {e.sub.length > 0 && (
                  <ul className="mt-2 flex flex-col gap-1.5 pl-4 border-l border-[var(--border)]">
                    {e.sub.map((s, i) => (
                      <li key={i} className="text-[12px] leading-5 text-[var(--text-secondary)]">
                        {s}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}

      <p className="mt-5 font-mono text-[10px] tracking-[0.14em] uppercase text-[var(--text-muted)]">
        {entries.length} entries · end of chronology
      </p>
    </article>
  );
}
