import { useQuery } from '@tanstack/react-query';
import { getUsage } from '../../api/usageApi';

function formatUsd(value: number): string {
  if (value >= 100) return `$${value.toFixed(0)}`;
  if (value >= 10) return `$${value.toFixed(1)}`;
  return `$${value.toFixed(2)}`;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export default function UsageBadge() {
  const { data } = useQuery({
    queryKey: ['usage'],
    queryFn: getUsage,
    refetchInterval: 30_000,
    staleTime: 15_000,
  });

  if (!data) return null;

  const usedPct = data.limit_usd > 0
    ? Math.min(100, Math.round((data.used_usd / data.limit_usd) * 100))
    : 0;

  // Colour ramp: <70 accent, 70-90 amber, >=90 red
  let barClass = 'bg-[var(--accent)]';
  let textClass = 'text-[var(--text-secondary)]';
  if (data.over_budget || usedPct >= 100) {
    barClass = 'bg-[var(--danger)]';
    textClass = 'text-[var(--danger)]';
  } else if (usedPct >= 90) {
    barClass = 'bg-[var(--danger)]';
    textClass = 'text-[var(--danger)]';
  } else if (usedPct >= 70) {
    barClass = 'bg-amber-400';
    textClass = 'text-amber-300';
  }

  const titleParts = [
    `Used: ${formatUsd(data.used_usd)} of ${formatUsd(data.limit_usd)}`,
    `Tokens: ${formatTokens(data.prompt_tokens)} in · ${formatTokens(data.completion_tokens)} out`,
    `Calls: ${data.total_calls}`,
  ];
  if (data.over_budget) titleParts.push('Budget exceeded — new requests are blocked.');

  return (
    <div
      className="hidden sm:flex items-center gap-2 px-2.5 py-1 rounded-md border border-[var(--border)] bg-[rgba(255,255,255,0.03)]"
      title={titleParts.join('\n')}
      aria-label="Usage budget"
    >
      <span className={`font-mono text-[10px] tracking-wider tabular-nums ${textClass}`}>
        {formatUsd(data.used_usd)}
        <span className="text-[var(--text-muted)]"> / {formatUsd(data.limit_usd)}</span>
      </span>
      <div className="w-12 h-1 rounded-full bg-[var(--bg-surface)] overflow-hidden">
        <div
          className={`h-full transition-[width] ${barClass}`}
          style={{ width: `${usedPct}%` }}
        />
      </div>
    </div>
  );
}
