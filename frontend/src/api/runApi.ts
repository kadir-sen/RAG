import apiClient from './client';

export interface QueryRun {
  run_id: string;
  username: string;
  module: string;
  query: string;
  route: string;
  status: string;
  created_at: string;
  latency_ms: number | null;
  total_steps: number | null;
  successful_steps: number | null;
  failed_steps: number | null;
  fallback_steps: number | null;
  llm_call_count: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  reasoning_tokens: number | null;
  cached_tokens: number | null;
  cost_usd?: number | null;
  source_count: number | null;
  footnote_count: number | null;
  metrics_complete: boolean;
}

export async function listRuns(): Promise<QueryRun[]> {
  const { data } = await apiClient.get<{ runs: QueryRun[] }>('/runs');
  return data.runs;
}
