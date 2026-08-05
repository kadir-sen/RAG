import { useEffect, useState } from 'react';
import { listRuns } from '../../api/runApi';
import type { QueryRun } from '../../api/runApi';
import { useAuthStore } from '../../stores/authStore';

const value = (n: number | null, suffix = '') => n == null ? 'unknown' : `${n.toLocaleString()}${suffix}`;

export default function QueryHistory({ projectId }: { projectId: string }) {
  const [runs, setRuns] = useState<QueryRun[]>([]);
  const isAdmin = useAuthStore((s) => s.user?.role === 'admin');
  useEffect(() => { void listRuns().then(setRuns).catch(() => setRuns([])); }, [projectId]);
  return (
    <section className="mt-6 border border-[var(--border)] bg-[var(--wash)] rounded-[3px] overflow-hidden">
      <div className="px-4 py-3 border-b border-[var(--border)]">
        <h2 className="text-[14px] font-semibold text-[var(--text-primary)]">Query and report history</h2>
        <p className="mt-1 text-[10px] text-[var(--text-muted)]">Legacy metrics that cannot be correlated are shown as unknown, never zero.</p>
      </div>
      <div data-testid="query-history-cards" className="max-h-80 overflow-y-auto md:hidden">
        {runs.map((run) => (
          <article key={run.run_id} className="border-b border-[var(--border)] bg-[var(--bg-primary)] p-4 last:border-b-0">
            <h3 className="line-clamp-2 text-[12px] font-medium text-[var(--text-primary)]">{run.query}</h3>
            <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 text-[10px]">
              <div><dt className="font-mono uppercase text-[var(--text-muted)]">Module</dt><dd className="mt-0.5 text-[var(--text-secondary)]">{run.module}</dd></div>
              <div><dt className="font-mono uppercase text-[var(--text-muted)]">Steps</dt><dd className="mt-0.5 text-[var(--text-secondary)]">{value(run.total_steps)}</dd></div>
              <div><dt className="font-mono uppercase text-[var(--text-muted)]">Model calls</dt><dd className="mt-0.5 text-[var(--text-secondary)]">{value(run.llm_call_count)}</dd></div>
              <div><dt className="font-mono uppercase text-[var(--text-muted)]">Latency</dt><dd className="mt-0.5 text-[var(--text-secondary)]">{run.latency_ms == null ? 'unknown' : `${(run.latency_ms / 1000).toFixed(1)}s`}</dd></div>
              <div><dt className="font-mono uppercase text-[var(--text-muted)]">Sources / notes</dt><dd className="mt-0.5 text-[var(--text-secondary)]">{value(run.source_count)} / {value(run.footnote_count)}</dd></div>
              {isAdmin && <div><dt className="font-mono uppercase text-[var(--text-muted)]">Cost</dt><dd className="mt-0.5 text-[var(--text-secondary)]">{run.cost_usd == null ? 'unknown' : `$${run.cost_usd.toFixed(5)}`}</dd></div>}
            </dl>
          </article>
        ))}
        {!runs.length && <p className="p-4 text-[11px] text-[var(--text-muted)]">No runs recorded for this project yet.</p>}
      </div>
      <div data-testid="query-history-table" className="hidden max-h-80 overflow-x-auto md:block">
        <table className="w-full text-left text-[10px]">
          <thead className="sticky top-0 bg-[var(--bg-primary)] text-[var(--text-muted)] font-mono uppercase"><tr><th className="p-2">Query</th><th className="p-2">Module</th><th className="p-2">Steps</th><th className="p-2">Model calls</th>{isAdmin && <th className="p-2">Cost</th>}<th className="p-2">Latency</th><th className="p-2">Sources / notes</th></tr></thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.run_id} className="border-t border-[var(--border)] text-[var(--text-secondary)]">
                <td className="p-2 max-w-[300px] truncate" title={run.query}>{run.query}</td>
                <td className="p-2">{run.module}</td>
                <td className="p-2">{value(run.total_steps)}</td>
                <td className="p-2">{value(run.llm_call_count)}</td>
                {isAdmin && <td className="p-2">{run.cost_usd == null ? 'unknown' : `$${run.cost_usd.toFixed(5)}`}</td>}
                <td className="p-2">{run.latency_ms == null ? 'unknown' : `${(run.latency_ms / 1000).toFixed(1)}s`}</td>
                <td className="p-2">{value(run.source_count)} / {value(run.footnote_count)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!runs.length && <p className="p-4 text-[11px] text-[var(--text-muted)]">No runs recorded for this project yet.</p>}
      </div>
    </section>
  );
}
