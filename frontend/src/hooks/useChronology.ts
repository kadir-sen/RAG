import { useQuery } from '@tanstack/react-query';
import {
  getChronologyEvents,
  getChronologyFacets,
  getChronologySummary,
} from '../api/chronologyApi';
import type { ChronologyFilters } from '../api/chronologyApi';

/* The event store only changes at ingest, so these can sit still for a while.
   Filters are part of the key, so narrowing refetches but going back to a
   filter you already used is instant. */
const STALE = 5 * 60 * 1000;

export function useChronologyEvents(filters: ChronologyFilters) {
  return useQuery({
    queryKey: ['chronology', 'events', filters],
    queryFn: () => getChronologyEvents(filters),
    staleTime: STALE,
  });
}

export function useChronologyFacets() {
  return useQuery({
    queryKey: ['chronology', 'facets'],
    queryFn: getChronologyFacets,
    staleTime: STALE,
  });
}

export function useChronologySummary() {
  return useQuery({
    queryKey: ['chronology', 'summary'],
    queryFn: getChronologySummary,
    staleTime: STALE,
  });
}
