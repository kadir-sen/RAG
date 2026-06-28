import { useQuery } from '@tanstack/react-query';
import { getQueryProgress } from '../api/chatApi';
import type { ActivityStep } from '../types/api';

/**
 * Poll the live activity feed for an in-flight query. Mirrors the indexing
 * live-stage polling (dynamic refetchInterval): polls ~every 900ms while the
 * request is enabled and not done, then stops. Returns the ordered steps so the
 * UI can show "reading X.pdf / analysing…" as the backend works.
 */
export function useActivityFeed(requestId: string | null, enabled: boolean) {
  const query = useQuery({
    queryKey: ['chatProgress', requestId],
    queryFn: () => getQueryProgress(requestId as string),
    enabled: enabled && !!requestId,
    refetchInterval: (q) => {
      if (!enabled) return false;
      return q.state.data?.done ? false : 900;
    },
    gcTime: 60_000,
  });

  return {
    steps: (query.data?.steps ?? []) as ActivityStep[],
    done: query.data?.done ?? false,
  };
}
