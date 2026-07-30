import apiClient from './client';
import { downloadGet } from './download';

/** One extracted event, as the store holds it. */
export interface ChronologyEvent {
  date: string;
  event_type: string;
  actor: string;
  reason: string;
  severity: string;
  status: string;
  description: string;
  file_name: string;
  doc_id: string;
}

export interface ChronologyFilters {
  eventType?: string | null;
  actor?: string | null;
  dateFrom?: string | null;
  dateTo?: string | null;
  limit?: number;
}

/** A page of events, plus how many the filters actually select. The two differ,
    often by a lot — the header needs `matching` so it describes the record
    rather than the page. */
export interface ChronologyEventPage {
  events: ChronologyEvent[];
  matching: number;
}

export async function getChronologyEvents(
  f: ChronologyFilters = {},
): Promise<ChronologyEventPage> {
  const { data } = await apiClient.get<{ events: ChronologyEvent[]; matching?: number }>(
    '/chronology/events',
    {
      params: {
        event_type: f.eventType || undefined,
        actor: f.actor || undefined,
        date_from: f.dateFrom || undefined,
        date_to: f.dateTo || undefined,
        limit: f.limit ?? 200,
      },
    },
  );
  return { events: data.events, matching: data.matching ?? data.events.length };
}

/** Event counts per type — only types that actually have events come back. */
export async function getChronologyFacets(): Promise<Record<string, number>> {
  const { data } = await apiClient.get<{ event_type: Record<string, number> }>(
    '/chronology/facets',
  );
  return data.event_type;
}

export async function getChronologySummary(): Promise<number> {
  const { data } = await apiClient.get<{ total_events: number }>('/chronology/summary');
  return data.total_events;
}

/* ── the authored chronologies ─────────────────────────────────────────
   Separate from the event store above: written narratives of a known issue,
   resolved by typing its subject. Matching is server-side and deterministic. */

export interface ChronologySubject {
  ref: string;
  title: string;
  summary: string;
}

export interface ChronologyEntry {
  ref: string;
  /** Pulled out of the sentence when it opens with one; "" for context entries. */
  date: string;
  text: string;
  sub: string[];
}

export type SubjectMatch =
  | { status: 'match'; subject: ChronologySubject; score?: number; entries: ChronologyEntry[] }
  | { status: 'ambiguous' | 'none'; candidates: ChronologySubject[] };

export async function listChronologySubjects(): Promise<{
  collection: string;
  subjects: ChronologySubject[];
}> {
  const { data } = await apiClient.get('/chronology/subjects');
  return data;
}

export async function matchChronologySubject(subject: string): Promise<SubjectMatch> {
  const { data } = await apiClient.post<SubjectMatch>('/chronology/match', { subject });
  return data;
}

export async function getChronologySubject(ref: string): Promise<SubjectMatch> {
  const { data } = await apiClient.get<SubjectMatch>(`/chronology/subjects/${ref}`);
  return data;
}

/* ── Word downloads ────────────────────────────────────────────────────
   The blob plumbing lives in ./download — the chat-answer export needs the same
   helper, and one copy of the content-disposition/Safari handling is enough. */

export async function downloadSubjectDocx(ref: string): Promise<void> {
  await downloadGet(
    `/chronology/subjects/${ref}/document`,
    `Chronology-${ref}.docx`,
  );
}

export async function downloadEventsDocx(f: ChronologyFilters = {}): Promise<void> {
  await downloadGet('/chronology/events/document', 'Chronology-project-record.docx', {
    event_type: f.eventType || undefined,
    actor: f.actor || undefined,
    date_from: f.dateFrom || undefined,
    date_to: f.dateTo || undefined,
  });
}

/* ── the staged, evidence-backed build ─────────────────────────────────
   /chronology/match stays the cheap resolver (candidate chips, ambiguity).
   This is the one that also resolves which corpus documents stand behind the
   narrative, and reports what it actually did. */

export interface EvidenceDocument {
  doc_id: string;
  file_name: string;
  page_number: number;
  anchor: string;
  snippet: string;
  score: number;
}

export interface EvidenceUnit {
  ref: string;
  kind: 'entry' | 'sub';
  date: string;
  documents: EvidenceDocument[];
  events: { date: string; event_type: string; actor: string; file_name: string; description: string }[];
  window: string[] | null;
}

export interface Evidence {
  ref: string;
  documents: EvidenceDocument[];
  units: EvidenceUnit[];
  passes: number;
  units_searched: number;
  dated_units: number;
  units_with_events: number;
  elapsed_ms: number;
  budget_exhausted: boolean;
  event_pad_days: number;
  corpus_searched: number;
  from_cache: boolean;
}

export type BuildResult =
  | {
      status: 'match';
      subject: ChronologySubject;
      entries: ChronologyEntry[];
      evidence: Evidence | null;
      evidence_note?: string;
      request_id?: string;
    }
  | { status: 'ambiguous' | 'none'; candidates: ChronologySubject[] };

export async function buildChronology(args: {
  subject?: string;
  ref?: string;
  requestId: string;
  force?: boolean;
}): Promise<BuildResult> {
  const { data } = await apiClient.post<BuildResult>(
    '/chronology/build',
    {
      subject: args.subject ?? '',
      ref: args.ref ?? '',
      request_id: args.requestId,
      force: args.force ?? false,
    },
    // The build searches the corpus per entry; the client's default 120s is
    // ample, but a cold full-text index build on a large corpus is not.
    { timeout: 5 * 60 * 1000 },
  );
  return data;
}
