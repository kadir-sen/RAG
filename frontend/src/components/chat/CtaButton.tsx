import { useState } from 'react';
import type { CallToAction } from '../../types/api';
import { reindexDataTables } from '../../api/adminApi';

interface Props {
  cta: CallToAction;
}

export default function CtaButton({ cta }: Props) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (cta.action !== 'reindex_data_tables') return null;

  const handleClick = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await reindexDataTables({ dryRun: false });
      if (res.dry_run === false) {
        setDone(`Reindexing ${res.scheduled} file(s) in background.`);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Reindex failed';
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  const excelCount = (cta.metadata?.excel_count as number | undefined) ?? 0;

  return (
    <div className="mt-3 p-3 rounded-lg border border-[var(--border)] bg-[var(--bg-primary)]/40">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="text-xs text-[var(--text-muted)]">
          {excelCount > 0
            ? `${excelCount} Excel/CSV file(s) detected — none registered as tables.`
            : 'No data tables registered yet.'}
        </div>
        <button
          onClick={handleClick}
          disabled={busy}
          className="px-3 py-1.5 text-xs rounded-lg bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] disabled:opacity-50 transition-colors"
        >
          {busy ? 'Scheduling…' : cta.label || 'Reindex'}
        </button>
      </div>
      {done && <div className="mt-2 text-[11px] text-emerald-400">{done}</div>}
      {error && <div className="mt-2 text-[11px] text-red-400">{error}</div>}
    </div>
  );
}
