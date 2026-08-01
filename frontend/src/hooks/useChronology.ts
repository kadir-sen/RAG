import { useQuery } from '@tanstack/react-query';
import {
  getChronologyEvents,
  getChronologyFacets,
  getChronologySummary,
} from '../api/chronologyApi';
import type { ChronologyFilters } from '../api/chronologyApi';
import { useProjectStore } from '../stores/projectStore';

/* The event store only changes at ingest, so these can sit still for a while.
   Filters are part of the key, so narrowing refetches but going back to a
   filter you already used is instant. */
const STALE = 5 * 60 * 1000;

export function useChronologyEvents(filters: ChronologyFilters) {
  const projectId = useProjectStore((state) => state.selectedProjectId);
  return useQuery({
    queryKey: ['chronology', projectId, 'events', filters],
    queryFn: () => getChronologyEvents(filters),
    enabled: Boolean(projectId),
    staleTime: STALE,
  });
}

export function useChronologyFacets() {
  const projectId = useProjectStore((state) => state.selectedProjectId);
  return useQuery({
    queryKey: ['chronology', projectId, 'facets'],
    queryFn: getChronologyFacets,
    enabled: Boolean(projectId),
    staleTime: STALE,
  });
}

export function useChronologySummary() {
  const projectId = useProjectStore((state) => state.selectedProjectId);
  return useQuery({
    queryKey: ['chronology', projectId, 'summary'],
    queryFn: getChronologySummary,
    enabled: Boolean(projectId),
    staleTime: STALE,
  });
}
