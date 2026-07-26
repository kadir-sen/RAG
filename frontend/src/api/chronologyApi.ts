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
