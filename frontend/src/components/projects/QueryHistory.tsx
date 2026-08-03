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
      <div className="overflow-x-auto max-h-80">
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
