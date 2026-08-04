import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { generateReport, listReports, previewChronologySources } from '../api/reportApi';
import type { ChronologySourcePreview, ReportJob } from '../api/reportApi';
import { useProjectStore } from '../stores/projectStore';

function message(error: unknown) {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (detail === 'project_has_no_ready_documents') return 'No searchable documents were found in this project.';
  if (typeof detail === 'object' && detail && 'error' in detail) return String((detail as { error: string }).error).replaceAll('_', ' ');
  return typeof detail === 'string' ? detail.replaceAll('_', ' ') : 'The chronology could not be queued.';
}

export default function ChronologyPage() {
  const navigate = useNavigate();
  const selectedProjectId = useProjectStore((state) => state.selectedProjectId);
  const project = useProjectStore((state) => state.projects.find((item) => item.project_id === state.selectedProjectId));
  const [topic, setTopic] = useState('');
  const [parties, setParties] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [jobs, setJobs] = useState<ReportJob[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState<ChronologySourcePreview | null>(null);
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [previewing, setPreviewing] = useState(false);

  useEffect(() => {
    setJobs([]); setPreview(null); setSelectedSources([]);
    if (selectedProjectId) void listReports('chronology').then(setJobs).catch(() => setError('Report history could not be loaded.'));
  }, [selectedProjectId]);

  const requestPayload = () => ({
    topic: topic.trim(), date_from: dateFrom, date_to: dateTo,
    parties: parties.split(',').map((value) => value.trim()).filter(Boolean),
  });

  const findSources = async () => {
    if (topic.trim().length < 3) return;
    setPreviewing(true); setError('');
    try {
      const next = await previewChronologySources(requestPayload());
      setPreview(next);
      setSelectedSources(next.documents.filter((doc) => doc.selected).map((doc) => doc.doc_id));
    } catch (caught) { setError(message(caught)); }
    finally { setPreviewing(false); }
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!topic.trim()) return;
    setSubmitting(true); setError('');
    try {
      const job = await generateReport('chronology', {
        ...requestPayload(), preparation_id: preview?.preparation_id || '',
        source_doc_ids: preview ? selectedSources : [],
      });
      navigate(job.report_url || `/chronology/reports/${job.job_id}`);
    } catch (caught) { setError(message(caught)); }
    finally { setSubmitting(false); }
  };

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-5xl mx-auto px-4 md:px-8 py-8">
        <p className="font-mono text-[10px] uppercase tracking-[.18em] text-[var(--text-muted)]">Module · Chronology</p>
        <h1 className="mt-2 text-2xl font-semibold text-[var(--text-primary)]">Build a new chronology</h1>
        <p className="mt-2 text-[13px] text-[var(--text-secondary)]">Research any issue across <strong>{project?.name}</strong>. Every request creates a permanent, English Word report with verified project sources.</p>

        <section className="mt-7 border border-[var(--border)] bg-[var(--wash)] p-5 md:p-7">
          <form onSubmit={submit} className="grid md:grid-cols-2 gap-3">
            <label className="md:col-span-2 text-[11px] text-[var(--text-secondary)]">Topic or research question
              <textarea required minLength={3} value={topic} onChange={(e) => { setTopic(e.target.value); setPreview(null); setSelectedSources([]); }} placeholder="Describe the issue, event or subject to investigate…" className="mt-2 block w-full min-h-28 border border-[var(--border)] bg-[var(--bg-primary)] p-3 text-[14px] text-[var(--text-primary)]" />
            </label>
            <label className="text-[11px] text-[var(--text-secondary)]">Start date (optional)<input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="mt-2 block w-full border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2 text-[12px]" /></label>
            <label className="text-[11px] text-[var(--text-secondary)]">End date (optional)<input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="mt-2 block w-full border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2 text-[12px]" /></label>
            <label className="md:col-span-2 text-[11px] text-[var(--text-secondary)]">Parties (optional, comma separated)<input value={parties} onChange={(e) => setParties(e.target.value)} placeholder="Employer, Contractor, Engineer" className="mt-2 block w-full border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2 text-[12px]" /></label>
            <div className="md:col-span-2 flex flex-wrap items-center justify-between gap-3 pt-2">
              <p className="text-[10px] text-[var(--text-muted)]">Reviewing sources improves coverage. You may also generate automatically.</p>
              <div className="flex gap-2"><button type="button" onClick={() => void findSources()} disabled={previewing || topic.trim().length < 3} className="border border-[var(--border)] px-4 py-3 font-mono text-[10px] uppercase disabled:opacity-40">{previewing ? 'Researching…' : 'Find source documents'}</button>
              <button disabled={submitting || !topic.trim() || project?.role === 'viewer' || Boolean(preview && selectedSources.length === 0)} className="px-6 py-3 bg-[var(--accent)] text-[var(--accent-ink)] font-mono text-[10px] uppercase tracking-[.14em] disabled:opacity-40">{submitting ? 'Queuing…' : 'Generate chronology →'}</button></div>
            </div>
          </form>
          {preview && <section className="mt-5 border-t border-[var(--border)] pt-5"><div className="flex items-center justify-between"><div><h2 className="text-[12px] font-semibold text-[var(--text-primary)]">Research source set</h2><p className="mt-1 text-[10px] text-[var(--text-muted)]">{selectedSources.length} selected · coverage {preview.coverage_status}</p></div><button type="button" onClick={() => setSelectedSources(preview.documents.map((doc) => doc.doc_id))} className="text-[10px] text-[var(--accent)]">Select all</button></div><div className="mt-3 max-h-72 overflow-auto border border-[var(--border)]">{preview.documents.map((doc) => <label key={`${doc.doc_id}:${doc.file_name}`} className="flex cursor-pointer items-start gap-3 border-b last:border-b-0 border-[var(--border)] bg-[var(--bg-primary)] p-3"><input type="checkbox" checked={selectedSources.includes(doc.doc_id)} onChange={(event) => setSelectedSources((current) => event.target.checked ? [...new Set([...current, doc.doc_id])] : current.filter((id) => id !== doc.doc_id))} /><span className="min-w-0"><span className="block truncate text-[11px] text-[var(--text-primary)]">{doc.file_name}</span><span className="mt-1 block font-mono text-[9px] text-[var(--text-muted)]">{doc.source_count} matched passages · {doc.pages.length} pages</span></span></label>)}</div></section>}
          {error && <p role="alert" className="mt-4 text-[11px] text-[var(--danger)]">{error}</p>}
        </section>

        <section className="mt-8">
          <div className="flex items-baseline justify-between"><h2 className="text-[15px] font-semibold text-[var(--text-primary)]">Project chronology reports</h2><span className="font-mono text-[9px] text-[var(--text-muted)]">{jobs.length} total</span></div>
          <div className="mt-3 border border-[var(--border)] bg-[var(--wash)]">
            {jobs.map((job) => <button type="button" key={job.job_id} onClick={() => navigate(job.report_url || `/chronology/reports/${job.job_id}`)} className="w-full grid sm:grid-cols-[90px_1fr_140px_90px] gap-3 items-center text-left border-b last:border-b-0 border-[var(--border)] bg-[var(--bg-primary)] px-4 py-3 hover:bg-[var(--wash)]"><span className="font-mono text-[10px] text-[var(--accent)]">6.{job.sequence_number}.x</span><span className="truncate text-[12px] text-[var(--text-primary)]">{job.title}</span><span className="font-mono text-[9px] text-[var(--text-muted)]">{new Date(job.created_at).toLocaleDateString('en-GB')}</span><span className={`font-mono text-[9px] uppercase ${job.status === 'failed' || job.status === 'credit_balance_exhausted' ? 'text-[var(--danger)]' : 'text-[var(--text-muted)]'}`}>{job.status.replaceAll('_', ' ')}</span></button>)}
            {jobs.length === 0 && <p className="p-5 text-[11px] text-[var(--text-muted)]">No chronology reports have been created for this project.</p>}
          </div>
        </section>
      </div>
    </div>
  );
}
