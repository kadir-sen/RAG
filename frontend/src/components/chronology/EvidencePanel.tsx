import FileTypeBadge from '../ui/FileTypeBadge';
import type { Evidence } from '../../api/chronologyApi';
import type { ViewerDoc } from '../../stores/uiStore';

/**
 * The corpus documents that stand behind an authored chronology.
 *
 * The narratives name no source files — 80 entries across the six of them and
 * not one filename — so until now "which document is 6.3.4 about?" had no
 * answer. These are the documents BM25 found for the subject and for each entry,
 * clickable straight into the viewer.
 *
 * The footer states what the build actually did. That is the counterweight to
 * pacing the step reveal: the display can take its time, but the numbers here are
 * the real ones.
 */
interface Props {
  evidence: Evidence | null;
  note?: string;
  onOpen: (doc: ViewerDoc) => void;
}

function seconds(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`;
}

export default function EvidencePanel({ evidence, note, onOpen }: Props) {
  if (!evidence) {
    return note ? (
      <p className="mt-6 text-[12px] text-[var(--text-muted)]">{note}</p>
    ) : null;
  }

  const {
    documents, passes, units_searched, dated_units, units_with_events,
    elapsed_ms, corpus_searched, event_pad_days, budget_exhausted, from_cache,
  } = evidence;

  return (
    <section className="mt-8 pt-5 border-t border-[var(--border)]">
      <p className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-muted)]">
        Supporting documents · {documents.length}
      </p>
      <p className="mt-1 text-[12px] text-[var(--text-secondary)] max-w-2xl">
        Resolved from the project record for this subject. The narrative itself
        names no files, so these are what the corpus offers behind it — ranked,
        not authored.
      </p>

      {documents.length === 0 ? (
        <p className="mt-3 text-[12px] text-[var(--text-muted)]">
          Nothing in the searchable corpus matched this subject.
        </p>
      ) : (
        <ul className="mt-3 flex flex-col divide-y divide-[var(--border)] list-none p-0">
          {documents.map((d) => (
            <li key={`${d.file_name}_${d.page_number}`}>
              <button
                type="button"
                onClick={() =>
                  onOpen({ docId: d.doc_id, fileName: d.file_name, anchor: d.anchor })
                }
                className="w-full text-left py-2.5 grid grid-cols-[auto_1fr_auto] items-start gap-x-3 hover:bg-[var(--wash)] transition-colors"
              >
                <FileTypeBadge extension={d.file_name.slice(d.file_name.lastIndexOf('.'))} size="sm" />
                <span className="min-w-0">
                  <span className="block font-mono text-[11px] text-[var(--text-primary)] truncate">
                    {d.file_name}
                  </span>
                  {d.snippet && (
                    <span className="block mt-0.5 text-[12px] leading-5 text-[var(--text-secondary)] line-clamp-2">
                      {d.snippet}
                    </span>
                  )}
                </span>
                <span className="font-mono text-[10px] tabular-nums text-[var(--text-muted)] pt-0.5 whitespace-nowrap">
                  p.{d.page_number} · open →
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {/* What actually happened. The step display is paced for reading; these
          numbers are not. */}
      <p className="mt-4 font-mono text-[10px] tracking-[0.14em] uppercase text-[var(--text-muted)] leading-5">
        {from_cache
          ? 'Reused from an earlier build'
          : `${seconds(elapsed_ms)} · ${passes} searches · ${units_searched} entries · ${corpus_searched.toLocaleString('en-GB')} documents searched`}
        {budget_exhausted && ' · budget reached, later entries not searched'}
      </p>
      {dated_units > 0 && (
        <p className="mt-1 font-mono text-[10px] tracking-[0.14em] uppercase text-[var(--text-muted)]">
          {units_with_events > 0
            ? `${units_with_events} of ${dated_units} dated entries matched extracted events (±${event_pad_days} days)`
            : `No extracted events fall in the periods these ${dated_units} dated entries name`}
        </p>
      )}
    </section>
  );
}
