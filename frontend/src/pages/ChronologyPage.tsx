import { Suspense, lazy, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import ChronologyTimeline from '../components/chronology/ChronologyTimeline';
import type { TimelineEvent } from '../utils/timeline';
import { formatTimelineLabel } from '../utils/timeline';
import { getFileTypeBadge } from '../styles/tokens';
import MonoTag from '../components/ui/MonoTag';
import Skeleton from '../components/shared/Skeleton';
import { useChronologyEvents, useChronologyFacets } from '../hooks/useChronology';
import type { ChronologyEvent } from '../api/chronologyApi';
import { useUIStore } from '../stores/uiStore';

const RightDocViewer = lazy(() => import('../components/viewer/RightDocViewer'));

/**
 * Chronology — its own area rather than a question you ask the chatbot.
 *
 * The events come straight from the store (src/event_timeline.py), so nothing
 * here goes near an LLM: the filters are a SQL WHERE clause and the list is
 * what came back. That is the point of pulling it out of the chat — a
 * chronology you are *reading* should be deterministic and the same every
 * time, not re-synthesised per question.
 */

/* The store's vocabulary, in the order a dispute tends to unfold. Chips are
   drawn from the facets response, so a type with no events never appears. */
const TYPE_ORDER = ['delay', 'disruption', 'excuse', 'decision', 'milestone', 'claim'];

/** Store row → the shape ChronologyTimeline already renders. */
function toTimelineEvents(rows: ChronologyEvent[]): TimelineEvent[] {
  return rows.map((r) => ({
    id: r.doc_id || undefined,
    date: r.date,
    label: formatTimelineLabel(r.date),
    type: r.event_type,
    badge: getFileTypeBadge(r.file_name),
    title: r.description || r.reason || r.file_name,
    who: r.actor || undefined,
    tag: r.event_type,
    note: r.reason || undefined,
    highlight: r.event_type === 'delay' || r.event_type === 'claim',
  }));
}

export default function ChronologyPage() {
  const [eventType, setEventType] = useState<string | null>(null);
  const [actor, setActor] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  const filters = useMemo(
    () => ({
      eventType,
      actor: actor.trim() || null,
      dateFrom: dateFrom || null,
      dateTo: dateTo || null,
    }),
    [eventType, actor, dateFrom, dateTo],
  );

  const { data: rows, isLoading, isError } = useChronologyEvents(filters);
  const { data: facets } = useChronologyFacets();

  const openDocument = useUIStore((s) => s.openDocument);
  const rightPanelOpen = useUIStore((s) => s.rightPanelOpen);

  const events = useMemo(() => toTimelineEvents(rows ?? []), [rows]);
  const total = useMemo(
    () => Object.values(facets ?? {}).reduce((a, b) => a + b, 0),
    [facets],
  );

  const chips = TYPE_ORDER.filter((t) => (facets?.[t] ?? 0) > 0);
  const filtered = Boolean(eventType || actor.trim() || dateFrom || dateTo);

  return (
    <div className="flex-1 flex min-h-0">
      {/* ── filters ────────────────────────────────────────────── */}
      <aside
        className="w-[240px] shrink-0 border-r border-[var(--border)] bg-[var(--bg-secondary)] overflow-y-auto p-4 hidden md:block"
        aria-label="Chronology filters"
      >
        <Link
          to="/"
          className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors no-underline"
        >
          ← modules
        </Link>

        <p className="mt-5 font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-muted)]">
          Event type
        </p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          <button type="button" onClick={() => setEventType(null)}>
            <MonoTag tone={eventType === null ? 'accent' : 'default'}>all · {total}</MonoTag>
          </button>
          {chips.map((t) => (
            <button key={t} type="button" onClick={() => setEventType(t === eventType ? null : t)}>
              <MonoTag tone={t === eventType ? 'accent' : 'default'}>
                {t} · {facets?.[t]}
              </MonoTag>
            </button>
          ))}
        </div>

        <label
          htmlFor="chron-actor"
          className="mt-6 block font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-muted)]"
        >
          Party
        </label>
        <input
          id="chron-actor"
          value={actor}
          onChange={(e) => setActor(e.target.value)}
          placeholder="any"
          className="mt-2 w-full px-2 py-1.5 rounded-[2px] bg-[var(--bg-input)] border border-[var(--border)] text-[12px] text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:border-[var(--ink)]"
        />

        <p className="mt-6 font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-muted)]">
          Period
        </p>
        <div className="mt-2 flex flex-col gap-2">
          <input
            type="date"
            aria-label="From date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="w-full px-2 py-1.5 rounded-[2px] bg-[var(--bg-input)] border border-[var(--border)] text-[12px] text-[var(--text-primary)] focus:outline-none focus:border-[var(--ink)]"
          />
          <input
            type="date"
            aria-label="To date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="w-full px-2 py-1.5 rounded-[2px] bg-[var(--bg-input)] border border-[var(--border)] text-[12px] text-[var(--text-primary)] focus:outline-none focus:border-[var(--ink)]"
          />
        </div>

        {filtered && (
          <button
            type="button"
            onClick={() => {
              setEventType(null);
              setActor('');
              setDateFrom('');
              setDateTo('');
            }}
            className="mt-5 font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
          >
            clear filters
          </button>
        )}
      </aside>

      {/* ── the timeline ───────────────────────────────────────── */}
      <div className="flex-1 min-w-0 overflow-y-auto">
        <div className="max-w-4xl mx-auto px-4 md:px-8 py-8">
          <header className="mb-6">
            <p className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-muted)]">
              Module · 01
            </p>
            <h1 className="mt-1.5 text-xl font-semibold tracking-tight text-[var(--text-primary)]">
              Chronology
            </h1>
            <p className="mt-1 text-[12px] text-[var(--text-secondary)]">
              {isLoading
                ? 'Reading the record…'
                : `${events.length} event${events.length === 1 ? '' : 's'}${filtered ? ' matching' : ' on file'}`}
            </p>
          </header>

          {isLoading && (
            <div className="flex flex-col gap-2" aria-busy="true">
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-14 w-full" />
            </div>
          )}

          {isError && (
            <div
              role="alert"
              className="rounded-[2px] border border-[var(--danger)] bg-[var(--wash)] px-3.5 py-2.5 text-[12px] text-[var(--text-primary)]"
            >
              The chronology could not be loaded. Try again shortly.
            </div>
          )}

          {!isLoading && !isError && events.length === 0 && (
            <div className="rounded-[2px] border border-[var(--border)] bg-[var(--wash)] px-4 py-6">
              <p className="text-[13px] text-[var(--text-primary)]">
                {filtered ? 'No events match these filters.' : 'No events on file yet.'}
              </p>
              <p className="mt-1.5 text-[12px] text-[var(--text-muted)]">
                {filtered
                  ? 'Widen the period or clear the party filter.'
                  : 'Events are extracted from documents as they are ingested. Documents added in bulk skip that step, so the record has to be enriched before it shows here.'}
              </p>
            </div>
          )}

          {!isLoading && !isError && events.length > 0 && (
            <ChronologyTimeline
              events={events}
              showFilters={false}
              caption="Project record"
              onEventClick={(e) =>
                e.id && openDocument({ docId: e.id, fileName: e.title })
              }
            />
          )}
        </div>
      </div>

      {/* ── the same viewer the chat uses ──────────────────────── */}
      {rightPanelOpen && (
        <div className="w-[340px] lg:w-[420px] shrink-0 border-l border-[var(--border)]">
          <Suspense fallback={null}>
            <RightDocViewer />
          </Suspense>
        </div>
      )}
    </div>
  );
}
