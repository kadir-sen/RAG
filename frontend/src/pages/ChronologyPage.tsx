import { Suspense, lazy, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import ChronologyTimeline from '../components/chronology/ChronologyTimeline';
import type { TimelineEvent } from '../utils/timeline';
import { getFileTypeBadge } from '../styles/tokens';
import MonoTag from '../components/ui/MonoTag';
import Skeleton from '../components/shared/Skeleton';
import { useChronologyEvents, useChronologyFacets } from '../hooks/useChronology';
import SubjectBar from '../components/chronology/SubjectBar';
import SubjectNarrative from '../components/chronology/SubjectNarrative';
import DownloadDocxButton from '../components/chronology/DownloadDocxButton';
import {
  buildChronology,
  downloadEventsDocx,
} from '../api/chronologyApi';
import type { BuildResult, Evidence } from '../api/chronologyApi';
import EvidencePanel from '../components/chronology/EvidencePanel';
import ActivityFeed from '../components/chat/ActivityFeed';
import { useActivityFeed } from '../hooks/useActivityFeed';
import { usePacedSteps } from '../hooks/usePacedSteps';
import type {
  ChronologyEvent,
  ChronologyEntry,
  ChronologySubject,
} from '../api/chronologyApi';
import { useUIStore } from '../stores/uiStore';
import { count } from '../utils/format';
import AIReportPanel from '../components/reports/AIReportPanel';

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
    // The file name, not doc_id. These events come from the bulk corpus, whose
    // documents have no registry entry — the viewer resolves them by file name
    // through its chunk-text fallback, and a hash doc_id simply misses. This is
    // the same substitution /library makes for the same documents
    // (backend/api/library.py:_vectors_only_library_docs).
    id: r.file_name || undefined,
    date: r.date,
    // Shown exactly as extracted. The store's dates are free-form because the
    // ingest kept whatever the document said — "1905", "1970 to 1975",
    // "28 March 2006". formatTimelineLabel assumes ISO and splits on
    // whitespace, which turned "1 June 2007" into "1" and invented a month for
    // "1905" ("Jan 1905"). Reformatting can only lose or fabricate here.
    label: r.date || '—',
    type: r.event_type,
    badge: getFileTypeBadge(r.file_name),
    title: r.description || r.reason || r.file_name,
    who: r.actor || undefined,
    tag: r.event_type,
    note: r.reason || undefined,
    highlight: r.event_type === 'delay' || r.event_type === 'claim',
    source: r.file_name || undefined,
  }));
}

export default function ChronologyPage() {
  /* Two ways in, and they do not mix: type a subject and read that issue's
     authored chronology, or leave the bar empty and browse the events the
     corpus produced. The narrative wins while one is open, because a
     chronology being read should not have a filter list competing with it. */
  const [subject, setSubject] = useState<ChronologySubject | null>(null);
  const [entries, setEntries] = useState<ChronologyEntry[]>([]);
  const [candidates, setCandidates] = useState<ChronologySubject[]>([]);
  const [barStatus, setBarStatus] = useState<'idle' | 'loading' | 'match' | 'ambiguous' | 'none'>('idle');
  const [lastSubject, setLastSubject] = useState('');

  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [evidenceNote, setEvidenceNote] = useState('');
  /* The build publishes its steps to the shared progress store under this id —
     the retrieval itself emits them, so each line names a document that was
     really read. */
  const [buildId, setBuildId] = useState<string | null>(null);
  const [building, setBuilding] = useState(false);
  const [pending, setPending] = useState<BuildResult | null>(null);
  const [lastRef, setLastRef] = useState('');

  const feed = useActivityFeed(buildId, building);
  const paced = usePacedSteps(feed.steps, { active: building });

  /* Hold the report until the paced reveal has caught up with the work. The
     steps are real; only the rhythm is ours, and the report's own footer prints
     the true elapsed time so nothing downstream inherits the pacing. */
  useEffect(() => {
    if (!building || !pending) return;
    if (!feed.done || !paced.caughtUp) return;
    if (pending.status === 'match') {
      setSubject(pending.subject);
      setEntries(pending.entries);
      setEvidence(pending.evidence);
      setEvidenceNote(pending.evidence_note ?? '');
      setCandidates([]);
      setBarStatus('match');
    } else {
      setSubject(null);
      setEntries([]);
      setCandidates(pending.candidates);
      setBarStatus(pending.status);
    }
    setBuilding(false);
    setPending(null);
  }, [building, pending, feed.done, paced.caughtUp]);

  const runBuild = async (args: { subject?: string; ref?: string; force?: boolean }) => {
    const rid = `chron-${Math.random().toString(36).slice(2, 10)}`;
    setBuildId(rid);
    setBuilding(true);
    setPending(null);
    setBarStatus('loading');
    setEvidence(null);
    setEvidenceNote('');
    try {
      const r = await buildChronology({ ...args, requestId: rid });
      if (r.status === 'match') setLastRef(r.subject.ref);
      // An immediate return (ambiguous, or no corpus to search) has nothing to
      // pace — showing a staged build in front of it would be theatre.
      if (r.status !== 'match' || r.evidence === null) {
        if (r.status === 'match') {
          setSubject(r.subject);
          setEntries(r.entries);
          setEvidence(null);
          setEvidenceNote(r.evidence_note ?? '');
          setCandidates([]);
          setBarStatus('match');
        } else {
          setSubject(null);
          setEntries([]);
          setCandidates(r.candidates);
          setBarStatus(r.status);
        }
        setBuilding(false);
        return;
      }
      setPending(r);
    } catch {
      setBuilding(false);
      setBarStatus('none');
      setCandidates([]);
    }
  };

  const handleSubject = async (s: string) => {
    setLastSubject(s);
    await runBuild({ subject: s });
  };

  const handlePick = async (ref: string) => {
    await runBuild({ ref });
  };

  const [eventType, setEventType] = useState<string | null>(null);
  const [actor, setActor] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  /* The store holds tens of thousands of events, so the list starts with a
     screenful and grows on request. A fixed cap would be a cap; this is a
     starting point, and "show more" walks it to the end of the record. */
  const PAGE = 200;
  const [limit, setLimit] = useState(PAGE);

  const filters = useMemo(
    () => ({
      eventType,
      actor: actor.trim() || null,
      dateFrom: dateFrom || null,
      dateTo: dateTo || null,
      limit,
    }),
    [eventType, actor, dateFrom, dateTo, limit],
  );

  /* Changing a filter starts the list over — carrying a grown limit into a new
     filter would load thousands of rows nobody asked to see. Wrapped rather
     than done in an effect so the change is one fetch, not two. */
  const pickType = (t: string | null) => { setEventType(t); setLimit(PAGE); };
  const pickActor = (a: string) => { setActor(a); setLimit(PAGE); };
  const pickFrom = (d: string) => { setDateFrom(d); setLimit(PAGE); };
  const pickTo = (d: string) => { setDateTo(d); setLimit(PAGE); };

  const { data: page, isLoading, isError } = useChronologyEvents(filters);
  const { data: facets } = useChronologyFacets();
  const rows = page?.events;
  /* How many the filters select, which is not how many this page carries — the
     store holds far more events than one request returns. Saying "200 events"
     when there are thousands describes the page as if it were the record. */
  const matching = page?.matching ?? 0;

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
          <button type="button" onClick={() => pickType(null)}>
            <MonoTag tone={eventType === null ? 'accent' : 'default'}>all · {total}</MonoTag>
          </button>
          {chips.map((t) => (
            <button key={t} type="button" onClick={() => pickType(t === eventType ? null : t)}>
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
          onChange={(e) => pickActor(e.target.value)}
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
            onChange={(e) => pickFrom(e.target.value)}
            className="w-full px-2 py-1.5 rounded-[2px] bg-[var(--bg-input)] border border-[var(--border)] text-[12px] text-[var(--text-primary)] focus:outline-none focus:border-[var(--ink)]"
          />
          <input
            type="date"
            aria-label="To date"
            value={dateTo}
            onChange={(e) => pickTo(e.target.value)}
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
              setLimit(PAGE);
            }}
            className="mt-5 font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
          >
            clear filters
          </button>
        )}
      </aside>

      {/* ── subject bar + whichever view it selected ───────────── */}
      <div className="flex-1 min-w-0 flex flex-col min-h-0">
        <AIReportPanel module="chronology" />
        <SubjectBar
          onSubmit={handleSubject}
          onPick={handlePick}
          status={barStatus}
          candidates={candidates}
          lastSubject={lastSubject}
        />
        <div className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto px-4 md:px-8 py-8">
          {building ? (
            /* The build in progress. Every line here was published by the
               retrieval as it ran, so it names a document that was really
               read — see usePacedSteps for why the reveal is paced. */
            <div className="mt-5">
              <p className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-muted)]">
                Building · {lastSubject || lastRef}
              </p>
              <p className="mt-1.5 text-[13px] text-[var(--text-secondary)]">
                Resolving the documents behind this chronology.
              </p>
              <div className="mt-4">
                <ActivityFeed steps={paced.visible} visible />
              </div>
            </div>
          ) : subject ? (
            <>
            <SubjectNarrative
              subject={subject}
              entries={entries}
              onClear={() => {
                setSubject(null);
                setEntries([]);
                setEvidence(null);
                setEvidenceNote('');
                setCandidates([]);
                setBarStatus('idle');
              }}
              onRebuild={() => runBuild({ ref: subject.ref, force: true })}
            />
            <EvidencePanel
              evidence={evidence}
              note={evidenceNote}
              onOpen={openDocument}
            />
            </>
          ) : (
          <>
          <header className="mb-6">
            <div className="flex items-baseline justify-between gap-4">
              <p className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-muted)]">
                Module · 01
              </p>
              {/* Downloads whatever the filters currently show, and the export
                  states those filters on its first page — an extract that does
                  not say it is one reads as the whole record. */}
              {!isLoading && !isError && events.length > 0 && (
                <DownloadDocxButton onDownload={() => downloadEventsDocx(filters)} />
              )}
            </div>
            <h1 className="mt-1.5 text-xl font-semibold tracking-tight text-[var(--text-primary)]">
              Chronology
            </h1>
            <p className="mt-1 text-[12px] text-[var(--text-secondary)]">
              {isLoading
                ? 'Reading the record…'
                : `${count(matching)} event${matching === 1 ? '' : 's'}${filtered ? ' matching' : ' on file'}`}
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
            <>
              <ChronologyTimeline
                events={events}
                showFilters={false}
                caption="Project record"
                onEventClick={(e) =>
                  e.id && openDocument({ docId: e.id, fileName: e.source || e.id })
                }
              />

              {/* The list starts at a screenful and walks to the end of the
                  record. Nothing here is withheld — the count above is the real
                  one, and the Word download always carries every event. */}
              {events.length < matching && (
                <div className="mt-6 flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => setLimit((n) => n + PAGE * 4)}
                    className="px-3 py-1.5 rounded-[2px] border border-[var(--border)] bg-[var(--wash)] font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-secondary)] hover:border-[var(--ink)] hover:text-[var(--text-primary)] transition-colors"
                  >
                    show more
                  </button>
                  <span className="font-mono text-[10px] tracking-[0.14em] uppercase text-[var(--text-muted)]">
                    {count(events.length)} of {count(matching)} shown
                  </span>
                </div>
              )}
            </>
          )}
          </>
          )}
        </div>
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
