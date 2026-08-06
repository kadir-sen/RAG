import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { downloadReport, getReport, resolveReportSource, retryReport } from '../api/reportApi';
import type { ReportJob, ResolvedReportSource } from '../api/reportApi';
import { useUIStore } from '../stores/uiStore';

export default function ChronologyReportPage() {
  const { jobId = '' } = useParams();
  const [job, setJob] = useState<ReportJob | null>(null);
  const [error, setError] = useState('');
  const [source, setSource] = useState<ResolvedReportSource | null>(null);
  const [retrying, setRetrying] = useState(false);
  const openDocument = useUIStore((state) => state.openDocument);
  const polling = job === null || job.status === 'queued' || job.status === 'processing';

  useEffect(() => {
    let live = true;
    const load = async () => {
      try { const next = await getReport(jobId); if (live) { setJob(next); setError(''); } }
      catch { if (live) setError('This report is unavailable in the active project.'); }
    };
    void load();
    const timer = polling ? window.setInterval(() => { void load(); }, 2200) : undefined;
    return () => { live = false; if (timer) window.clearInterval(timer); };
  }, [jobId, polling]);

  const entries = useMemo(() => Array.isArray(job?.result?.entries) ? job?.result?.entries as Array<Record<string, unknown>> : [], [job]);
  const evidence = useMemo(() => Array.isArray(job?.result?.evidence) ? job?.result?.evidence as Array<Record<string, unknown>> : [], [job]);
  const showSource = async (sourceId: string) => {
    try { setSource(await resolveReportSource(jobId, sourceId)); }
    catch { setError('The selected source no longer resolves inside this project.'); }
  };
  const retry = async () => {
    setRetrying(true); setError('');
    try { setJob(await retryReport(jobId)); }
    catch { setError('This report could not be retried yet.'); }
    finally { setRetrying(false); }
  };
  const sourceAnchor = (item: Record<string, unknown>) => {
    if (item.kind === 'excel' && item.sheet && item.row_from) {
      return `sheet_${String(item.sheet)}_rows_${Number(item.row_from)}_${Number(item.row_to || item.row_from)}`;
    }
    return item.page ? `page_${Number(item.page)}` : undefined;
  };
  const openProjectSource = () => {
    if (!source?.record.doc_id) return;
    openDocument({
      docId: source.record.doc_id,
      fileName: source.record.file_name || String(source.source.file_name || ''),
      anchor: sourceAnchor(source.source),
      highlightText: String(source.source.excerpt || ''),
    });
  };

  if (error && !job) return <div className="p-8"><p className="text-[var(--danger)]">{error}</p><Link to="/chronology" className="mt-4 inline-block text-[var(--accent)]">← Back to chronology</Link></div>;
  if (!job) return <div className="p-8 text-[12px] text-[var(--text-muted)]">Loading report…</div>;

  const active = job.status === 'queued' || job.status === 'processing';
  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-5xl mx-auto px-3 py-5 sm:px-4 md:px-8 md:py-8">
        <Link to="/chronology" className="inline-flex min-h-11 items-center font-mono text-[10px] uppercase text-[var(--text-muted)]">← All chronologies</Link>
        <div className="mt-5 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div><p className="font-mono text-[10px] text-[var(--accent)]">CHRONOLOGY · 6.{job.sequence_number}</p><h1 className="mt-2 text-2xl font-semibold text-[var(--text-primary)]">{job.title}</h1><p className="mt-2 text-[11px] text-[var(--text-muted)]">Created {new Date(job.created_at).toLocaleString('en-GB')} · read-only record</p></div>
          {job.status === 'ready' && <button type="button" onClick={() => void downloadReport(job)} className="min-h-11 w-full shrink-0 bg-[var(--accent)] px-5 py-3 font-mono text-[10px] uppercase tracking-[.12em] text-[var(--accent-ink)] sm:w-auto">Download Word ↓</button>}
        </div>

        {active && <section className="mt-7 border border-[var(--border)] bg-[var(--wash)] p-5"><div className="flex justify-between text-[11px]"><span className="text-[var(--text-primary)]">{job.stage.replaceAll('_', ' ')}</span><span className="font-mono text-[var(--text-muted)]">{Math.round(job.progress * 100)}%</span></div><div className="mt-3 h-1 bg-[var(--wash-firm)]"><div className="h-full bg-[var(--accent)] transition-all" style={{ width: `${job.progress * 100}%` }} /></div><p className="mt-3 text-[10px] text-[var(--text-muted)]">This URL is permanent. You may leave and return while the report is being prepared.</p></section>}
        {(job.status === 'failed' || job.status === 'credit_balance_exhausted') && <section role="alert" className="mt-7 border border-[var(--danger)] p-5 text-[12px] text-[var(--danger)]"><p>{job.status === 'credit_balance_exhausted' ? 'Credit balance exhausted. Add credits, then retry the report.' : (job.error || 'Report generation failed.')}</p>{job.retryable && <button type="button" disabled={retrying} onClick={() => void retry()} className="mt-4 border border-[var(--danger)] px-4 py-2 font-mono text-[10px] uppercase disabled:opacity-40">{retrying ? 'Queuing…' : 'Retry same report'}</button>}</section>}

        {job.status === 'ready' && <div className="mt-8 grid lg:grid-cols-[1fr_280px] gap-6">
          <main className="min-w-0 space-y-4">{entries.map((entry, index) => <article key={index} className="min-w-0 border border-[var(--border)] bg-[var(--bg-primary)] p-4 md:p-5"><p className="break-words font-mono text-[10px] text-[var(--accent)]">6.{job.sequence_number}.{index + 1} · {String(entry.event_date || (index === 0 ? 'Overview' : 'Date not established'))}</p>{(Array.isArray(entry.claims) ? entry.claims as Array<Record<string, unknown>> : []).map((claim, claimIndex) => <p key={claimIndex} className="mt-3 break-words text-[13px] leading-6 text-[var(--text-primary)]">{String(claim.text || '')} <span className="inline-flex flex-wrap gap-1">{(Array.isArray(claim.source_ids) ? claim.source_ids as string[] : []).map((id) => <button type="button" key={id} onClick={() => void showSource(id)} className="inline-flex min-h-11 items-center font-mono text-[9px] text-[var(--accent)] hover:underline md:min-h-0">[{id}]</button>)}</span></p>)}</article>)}</main>
          <aside><p className="font-mono text-[10px] uppercase tracking-[.14em] text-[var(--text-muted)]">Verified sources · {evidence.length}</p><div className="mt-3 space-y-2">{evidence.map((item) => <button type="button" key={String(item.source_id)} onClick={() => void showSource(String(item.source_id))} className="w-full border border-[var(--border)] bg-[var(--wash)] p-3 text-left"><span className="block truncate text-[11px] text-[var(--text-primary)]">{String(item.file_name || item.title || '')}</span><span className="mt-1 block font-mono text-[9px] text-[var(--text-muted)]">{String(item.source_id)}{item.page ? ` · p.${item.page}` : ''}{item.sheet ? ` · ${String(item.sheet)} rows ${String(item.row_from)}–${String(item.row_to)}` : ''}</span></button>)}</div></aside>
        </div>}

        {source && <section aria-label="Source preview" className="fixed inset-x-0 bottom-0 z-40 max-h-[72dvh] overflow-auto border border-[var(--ink)] bg-[var(--bg-primary)] p-4 pb-[max(1rem,env(safe-area-inset-bottom))] shadow-xl sm:inset-x-4 sm:bottom-4 sm:mx-auto sm:max-w-3xl"><div className="flex justify-between gap-4"><div className="min-w-0"><p className="break-words text-[12px] font-semibold text-[var(--text-primary)]">{String(source.source.file_name || source.record.file_name || 'Project source')}</p><p className="mt-2 max-h-40 overflow-auto text-[11px] leading-5 text-[var(--text-secondary)]">{String(source.source.excerpt || '')}</p></div><button type="button" onClick={() => setSource(null)} className="flex h-11 w-11 shrink-0 items-center justify-center self-start text-[var(--text-muted)]" aria-label="Close source preview">×</button></div>{source.record.doc_id && <button type="button" onClick={openProjectSource} className="mt-3 min-h-11 w-full border border-[var(--border)] px-3 text-[10px] text-[var(--accent)] sm:w-auto">Open project document →</button>}</section>}
        {error && <p role="alert" className="mt-5 text-[11px] text-[var(--danger)]">{error}</p>}
      </div>
    </div>
  );
}
