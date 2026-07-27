import apiClient from './client';

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

export async function getChronologyEvents(
  f: ChronologyFilters = {},
): Promise<ChronologyEvent[]> {
  const { data } = await apiClient.get<{ events: ChronologyEvent[] }>('/chronology/events', {
    params: {
      event_type: f.eventType || undefined,
      actor: f.actor || undefined,
      date_from: f.dateFrom || undefined,
      date_to: f.dateTo || undefined,
      limit: f.limit ?? 200,
    },
  });
  return data.events;
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
