import { useEffect, useMemo, useState } from 'react';
import { getTrustGuardStats } from '../../api/adminApi';
import type { TrustGuardStats } from '../../types/api';

interface Props {
  open: boolean;
  onClose: () => void;
}

const ACTION_LABELS: Record<string, string> = {
  approve: 'Approved',
  approve_with_caveats: 'Approved with caveats',
  rewrite: 'Rewritten',
  refuse: 'Refused',
};

const SKIP_LABELS: Record<string, string> = {
  risk_below_threshold: 'Low risk',
  route_excluded: 'Route excluded (SQL / lists)',
  selected_context: 'Selected context',
  greeting: 'Greeting',
  empty_answer: 'Empty answer',
  disabled: 'Guard disabled',
  error: 'Guard error (failed open)',
};

export default function TrustGuardPanel({ open, onClose }: Props) {
  const [stats, setStats] = useState<TrustGuardStats | null>(null);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = async (windowDays = days) => {
    setLoading(true);
    setError(null);
    try {
      const data = await getTrustGuardStats(windowDays);
      setStats(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load stats');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      void refresh();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const tiles = useMemo(() => {
    if (!stats) return null;
    return [
      { label: 'Queries', value: stats.total_runs },
      { label: 'Verified runs', value: stats.guarded, tone: 'good' as const },
      { label: 'Coverage', value: `${stats.coverage_pct}%` },
      { label: 'Avg latency', value: `${(stats.avg_latency_ms / 1000).toFixed(1)}s` },
      { label: 'p95 latency', value: `${(stats.p95_latency_ms / 1000).toFixed(1)}s` },
      { label: 'Avg LLM calls', value: stats.avg_llm_calls },
      {
        label: 'Entity catches',
        value: stats.catches.unknown_entity_runs,
        tone: 'warn' as const,
      },
      {
        label: 'Rewrites/refusals',
        value: stats.catches.rewrites_or_refusals,
        tone: 'warn' as const,
      },
    ];
  }, [stats]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl shadow-2xl w-[min(960px,95vw)] max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-[var(--border)]">
          <div>
            <h2 className="text-sm font-semibold text-[var(--text-primary)]">
              Trust Guard
            </h2>
            <p className="text-[11px] text-[var(--text-muted)]">
              Answer verification coverage, actions and latency
            </p>
          </div>
          <div className="flex items-center gap-2">
            <select
              value={days}
              onChange={(e) => {
                const d = Number(e.target.value);
                setDays(d);
                void refresh(d);
              }}
              className="text-xs bg-[var(--bg-primary)] border border-[var(--border)] rounded-md px-2 py-1 text-[var(--text-secondary)]"
              aria-label="Time window"
            >
              <option value={7}>Last 7 days</option>
              <option value={30}>Last 30 days</option>
              <option value={90}>Last 90 days</option>
            </select>
            <button
              onClick={() => void refresh()}
              disabled={loading}
              className="px-3 py-1.5 text-xs rounded-md border border-[var(--border)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
            >
              Refresh
            </button>
            <button
              onClick={onClose}
              className="text-[var(--text-muted)] hover:text-[var(--text-primary)] text-lg leading-none ml-1"
              aria-label="Close"
            >
              ×
            </button>
          </div>
        </div>

        {/* Summary tiles */}
        <div className="flex flex-wrap gap-2 px-5 py-3 border-b border-[var(--border)] bg-[var(--bg-primary)]/40">
          {loading && <span className="text-xs text-[var(--text-muted)]">Loading…</span>}
          {tiles?.map((t) => (
            <div
              key={t.label}
              className={
                'px-3 py-1.5 rounded-md border text-xs ' +
                (t.tone === 'good'
                  ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
                  : t.tone === 'warn'
                    ? 'border-amber-500/40 bg-amber-500/10 text-amber-300'
                    : 'border-[var(--border)] bg-[var(--bg-primary)]/60 text-[var(--text-secondary)]')
              }
            >
              <span className="font-semibold mr-1">{t.value}</span>
              <span className="text-[10px] uppercase tracking-wide opacity-80">
                {t.label}
              </span>
            </div>
          ))}
        </div>

        {/* Action + skip breakdowns */}
        {stats && (
          <div className="px-5 py-2 border-b border-[var(--border)] text-[11px] text-[var(--text-muted)] flex flex-wrap gap-x-6 gap-y-1">
            <span>
              <span className="opacity-70 mr-2">Actions:</span>
              {Object.entries(stats.actions).length === 0 && '—'}
              {Object.entries(stats.actions).map(([k, v]) => (
                <span key={k} className="mr-3">
                  <span className="text-[var(--text-secondary)] font-medium">{v}</span>{' '}
                  <span className="opacity-70">{ACTION_LABELS[k] ?? k}</span>
                </span>
              ))}
            </span>
            <span>
              <span className="opacity-70 mr-2">Skipped:</span>
              {Object.entries(stats.skip_reasons).length === 0 && '—'}
              {Object.entries(stats.skip_reasons).map(([k, v]) => (
                <span key={k} className="mr-3">
                  <span className="text-[var(--text-secondary)] font-medium">{v}</span>{' '}
                  <span className="opacity-70">{SKIP_LABELS[k] ?? k}</span>
                </span>
              ))}
            </span>
          </div>
        )}

        {error && (
          <div className="px-5 py-2 text-xs text-red-400 border-b border-[var(--border)]">
            {error}
          </div>
        )}

        {/* Recent runs */}
        <div className="flex-1 overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-[var(--bg-primary)] z-10">
              <tr className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                <th className="text-left px-4 py-2">Query</th>
                <th className="text-left px-3 py-2">Route</th>
                <th className="text-left px-3 py-2">Risk</th>
                <th className="text-left px-3 py-2">Outcome</th>
                <th className="text-right px-3 py-2">Latency</th>
              </tr>
            </thead>
            <tbody>
              {stats?.recent.map((r, i) => (
                <tr
                  key={`${r.ts}-${i}`}
                  className="border-b border-[var(--border)]/60 hover:bg-[var(--bg-hover)]"
                >
                  <td className="px-4 py-2 text-[var(--text-primary)] truncate max-w-[320px]">
                    {r.query}
                  </td>
                  <td className="px-3 py-2 text-[var(--text-secondary)]">{r.route || '—'}</td>
                  <td className="px-3 py-2 text-[var(--text-secondary)]">{r.risk || '—'}</td>
                  <td className="px-3 py-2">
                    {r.skipped ? (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-500/20 text-zinc-300 border border-zinc-500/30 font-semibold">
                        SKIPPED · {SKIP_LABELS[r.skipped_reason] ?? r.skipped_reason}
                      </span>
                    ) : (
                      <OutcomePill action={r.action} />
                    )}
                  </td>
                  <td className="px-3 py-2 text-right text-[var(--text-secondary)]">
                    {r.skipped ? '—' : `${(r.latency_ms / 1000).toFixed(1)}s`}
                  </td>
                </tr>
              ))}
              {stats && stats.recent.length === 0 && (
                <tr>
                  <td
                    colSpan={5}
                    className="px-4 py-8 text-center text-[var(--text-muted)]"
                  >
                    No Trust Guard runs recorded yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function OutcomePill({ action }: { action: string }) {
  if (action === 'approve') {
    return (
      <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-semibold">
        VERIFIED
      </span>
    );
  }
  if (action === 'approve_with_caveats') {
    return (
      <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30 font-semibold">
        CAVEATS
      </span>
    );
  }
  if (action === 'rewrite') {
    return (
      <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30 font-semibold">
        REWRITTEN
      </span>
    );
  }
  if (action === 'refuse') {
    return (
      <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/20 text-red-300 border border-red-500/30 font-semibold">
        REFUSED
      </span>
    );
  }
  return (
    <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-500/20 text-zinc-300 border border-zinc-500/30 font-semibold">
      {action?.toUpperCase() || '—'}
    </span>
  );
}
