import api from './client';

export interface UsageSnapshot {
  used_usd: number;
  limit_usd: number;
  remaining_usd: number;
  remaining_pct: number;
  over_budget: boolean;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  total_calls: number;
}

export async function getUsage(): Promise<UsageSnapshot> {
  const { data } = await api.get<UsageSnapshot>('/usage');
  return data;
}
