import { useEffect, useMemo, useState } from 'react';
import {
  diagnoseDataTable,
  getDataTablesStatus,
  reindexDataTables,
} from '../../api/adminApi';
import type {
  DataTablesStatus,
  DiagnoseResult,
  ReindexResult,
} from '../../types/api';

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function DataTablesPanel({ open, onClose }: Props) {
  const [status, setStatus] = useState<DataTablesStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [reindexResult, setReindexResult] = useState<ReindexResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [diagnosis, setDiagnosis] = useState<DiagnoseResult | null>(null);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getDataTablesStatus();
      setStatus(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load status');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      void refresh();
    }
  }, [open]);

  const handleReindex = async (dryRun: boolean) => {
    setReindexing(true);
    setError(null);
    setReindexResult(null);
    try {
      const res = await reindexDataTables({ dryRun });
      setReindexResult(res);
      if (!dryRun) {
        // Refresh status after a short delay so background tasks can finish
        setTimeout(() => void refresh(), 2000);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Reindex failed');
    } finally {
      setReindexing(false);
    }
  };

  const handleDiagnose = async (fileId: string) => {
    setError(null);
    setDiagnosis(null);
    try {
      const res = await diagnoseDataTable(fileId);
      setDiagnosis(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Diagnose failed');
    }
  };

  const summary = useMemo(() => {
    if (!status) return null;
    return [
      { label: 'Excel/CSV', value: status.total_data_files },
      { label: 'Registered', value: status.registered, tone: 'good' as const },
      { label: 'No match', value: status.no_schema_match, tone: 'warn' as const },
      { label: 'Errors', value: status.error, tone: 'bad' as const },
      { label: 'DuckDB tables', value: status.duckdb_tables_loaded },
      { label: 'Parquets', value: status.parquet_files },
    ];
  }, [status]);

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
              Data Tables (SQL)
            </h2>
            <p className="text-[11px] text-[var(--text-muted)]">
              Excel/CSV ingestion status and reindex tools
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-[var(--text-muted)] hover:text-[var(--text-primary)] text-lg leading-none"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* Summary bar */}
        <div className="flex flex-wrap gap-2 px-5 py-3 border-b border-[var(--border)] bg-[var(--bg-primary)]/40">
          {loading && <span className="text-xs text-[var(--text-muted)]">Loading…</span>}
          {summary?.map((s) => (
            <div
              key={s.label}
              className={
                'px-3 py-1.5 rounded-md border text-xs ' +
                (s.tone === 'good'
                  ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
                  : s.tone === 'warn'
                    ? 'border-amber-500/40 bg-amber-500/10 text-amber-300'
                    : s.tone === 'bad'
                      ? 'border-red-500/40 bg-red-500/10 text-red-300'
                      : 'border-[var(--border)] bg-[var(--bg-primary)]/60 text-[var(--text-secondary)]')
              }
            >
              <span className="font-semibold mr-1">{s.value}</span>
              <span className="text-[10px] uppercase tracking-wide opacity-80">
                {s.label}
              </span>
            </div>
          ))}
          <div className="ml-auto flex gap-2">
            <button
              onClick={() => handleReindex(true)}
              disabled={reindexing}
              className="px-3 py-1.5 text-xs rounded-md border border-[var(--border)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
            >
              Dry run
            </button>
            <button
              onClick={() => handleReindex(false)}
              disabled={reindexing}
              className="px-3 py-1.5 text-xs rounded-md bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] disabled:opacity-50"
            >
              {reindexing ? 'Working…' : 'Reindex unregistered'}
            </button>
            <button
              onClick={() => void refresh()}
              disabled={loading}
              className="px-3 py-1.5 text-xs rounded-md border border-[var(--border)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
            >
              Refresh
            </button>
          </div>
        </div>

        {/* Schema breakdown */}
        {status && Object.keys(status.schema_summary).length > 0 && (
          <div className="px-5 py-2 border-b border-[var(--border)] text-[11px] text-[var(--text-muted)] flex flex-wrap gap-3">
            <span className="opacity-70">By schema:</span>
            {Object.entries(status.schema_summary).map(([k, v]) => (
              <span key={k}>
                <span className="text-[var(--text-secondary)] font-medium">{v}</span>{' '}
                <span className="opacity-70">{k}</span>
              </span>
            ))}
          </div>
        )}

        {error && (
          <div className="px-5 py-2 text-xs text-red-400 border-b border-[var(--border)]">
            {error}
          </div>
        )}

        {reindexResult && (
          <div className="px-5 py-2 text-[11px] text-[var(--text-secondary)] border-b border-[var(--border)] bg-[var(--bg-primary)]/40">
            {reindexResult.dry_run ? (
              <>
                Dry run: {reindexResult.would_register}/
                {reindexResult.total_targets} would register.
              </>
            ) : (
              <>
                Scheduled {reindexResult.scheduled} file(s) to reindex in
                background. Refresh in a few seconds.
              </>
            )}
          </div>
        )}

        {/* File list */}
        <div className="flex-1 overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-[var(--bg-primary)] z-10">
              <tr className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                <th className="text-left px-4 py-2">File</th>
                <th className="text-left px-3 py-2">Status</th>
                <th className="text-right px-3 py-2">Tables</th>
                <th className="text-left px-3 py-2">Tables registered</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {status?.files.map((f) => (
                <tr
                  key={f.file_id}
                  className="border-b border-[var(--border)]/60 hover:bg-[var(--bg-hover)]"
                >
                  <td className="px-4 py-2 text-[var(--text-primary)] truncate max-w-[280px]">
                    {f.file_name}
                  </td>
                  <td className="px-3 py-2">
                    <StatusPill status={f.data_table_status} />
                  </td>
                  <td className="px-3 py-2 text-right text-[var(--text-secondary)]">
                    {f.data_tables_count}
                  </td>
                  <td className="px-3 py-2 text-[10px] text-[var(--text-muted)] truncate max-w-[260px]">
                    {f.table_names.join(', ') || '—'}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      onClick={() => void handleDiagnose(f.file_id)}
                      className="text-[10px] underline text-[var(--accent)] hover:text-[var(--accent-hover)]"
                    >
                      Diagnose
                    </button>
                  </td>
                </tr>
              ))}
              {status && status.files.length === 0 && (
                <tr>
                  <td
                    colSpan={5}
                    className="px-4 py-8 text-center text-[var(--text-muted)]"
                  >
                    No Excel/CSV files in registry.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Diagnose panel */}
        {diagnosis && (
          <div className="border-t border-[var(--border)] bg-[var(--bg-primary)]/60 px-5 py-3 max-h-64 overflow-y-auto">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-semibold text-[var(--text-primary)]">
                Diagnose: {diagnosis.file?.name ?? '(file)'}
              </h3>
              <button
                onClick={() => setDiagnosis(null)}
                className="text-[10px] text-[var(--text-muted)] hover:text-[var(--text-primary)]"
              >
                close
              </button>
            </div>
            {!diagnosis.ok && (
              <p className="text-[11px] text-red-400">{diagnosis.error}</p>
            )}
            {diagnosis.sheets?.map((s) => (
              <div key={s.sheet} className="mb-2 text-[11px]">
                <p className="text-[var(--text-secondary)]">
                  <span className="font-semibold">{s.sheet}</span>
                  {s.rows != null && <> · {s.rows} rows</>}
                  {s.best_schema ? (
                    <span className="ml-2 text-emerald-400">
                      → {s.best_schema} ({s.best_ratio})
                    </span>
                  ) : (
                    <span className="ml-2 text-amber-400">no match</span>
                  )}
                </p>
                {s.schema_matches && s.schema_matches.length > 0 && (
                  <ul className="ml-3 text-[10px] text-[var(--text-muted)]">
                    {s.schema_matches.map((m) => (
                      <li key={m.schema_id}>
                        {m.schema_id}: {m.ratio} (matched {m.matched.length}, missing{' '}
                        {m.missing.length === 0 ? '0' : m.missing.join(', ')})
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function StatusPill({ status }: { status: string | null | undefined }) {
  if (status === 'registered') {
    return (
      <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-semibold">
        REGISTERED
      </span>
    );
  }
  if (status === 'no_schema_match') {
    return (
      <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-500/20 text-zinc-300 border border-zinc-500/30 font-semibold">
        NO MATCH
      </span>
    );
  }
  if (status === 'error') {
    return (
      <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/20 text-red-300 border border-red-500/30 font-semibold">
        ERROR
      </span>
    );
  }
  return (
    <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30 font-semibold">
      PENDING
    </span>
  );
}
