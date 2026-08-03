import { useEffect, useState } from 'react';
import { downloadReport, generateReport, getReport, listReports, listToolkitEvidence, saveForensicDraft } from '../../api/reportApi';
import type { ReportJob } from '../../api/reportApi';
import type { ToolkitArtifact } from '../../api/reportApi';
import { useProjectStore } from '../../stores/projectStore';

export default function AIReportPanel({ module }: { module: 'chronology' | 'forensic' }) {
  const projects = useProjectStore((state) => state.projects);
  const selectedProjectId = useProjectStore((state) => state.selectedProjectId);
  const canEdit = projects.find((project) => project.project_id === selectedProjectId)?.role !== 'viewer';
  const [topic, setTopic] = useState('');
  const [parties, setParties] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [issueStatus, setIssueStatus] = useState<'Draft' | 'Issue'>('Draft');
  const [jobs, setJobs] = useState<ReportJob[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [draftSections, setDraftSections] = useState<Record<string, Array<Record<string, unknown>>>>({});
  const [toolkitArtifacts, setToolkitArtifacts] = useState<ToolkitArtifact[]>([]);
  const [selectedToolkit, setSelectedToolkit] = useState<string[]>([]);

  useEffect(() => {
    setJobs([]);
    setReviewing(null);
    if (selectedProjectId) void listReports(module).then(setJobs).catch(() => undefined);
  }, [module, selectedProjectId]);
  useEffect(() => {
    setToolkitArtifacts([]);
    setSelectedToolkit([]);
    if (module === 'forensic' && selectedProjectId) void listToolkitEvidence().then(setToolkitArtifacts).catch(() => setToolkitArtifacts([]));
  }, [module, selectedProjectId]);
  useEffect(() => {
    if (!jobs.some((job) => job.status === 'queued' || job.status === 'processing')) return;
    const timer = window.setInterval(async () => {
      const next = await Promise.all(jobs.map((job) =>
        job.status === 'queued' || job.status === 'processing' ? getReport(job.job_id) : job,
      ));
      setJobs(next);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [jobs]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!topic.trim()) return;
    setSubmitting(true); setError('');
    try {
      const common = {
        topic: topic.trim(), date_from: dateFrom, date_to: dateTo,
        parties: parties.split(',').map((v) => v.trim()).filter(Boolean),
      };
      const job = await generateReport(module, module === 'chronology'
        ? common
        : { ...common, status: issueStatus, toolkit_artifact_ids: selectedToolkit });
      setJobs((current) => [job, ...current]);
      setTopic('');
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'The report could not be queued. Finish document processing first.');
    } finally { setSubmitting(false); }
  };

  const openReview = (job: ReportJob) => {
    setReviewing((current) => current === job.job_id ? null : job.job_id);
    const sections = job.result?.sections;
    if (module === 'forensic' && sections && typeof sections === 'object') {
      setDraftSections(sections as Record<string, Array<Record<string, unknown>>>);
    }
  };

  const saveReview = async (job: ReportJob, issue: boolean) => {
    try {
      const saved = await saveForensicDraft(job.job_id, draftSections, issue);
      setJobs((current) => current.map((item) => item.job_id === saved.job_id ? saved : item));
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'The reviewed draft could not be saved.');
    }
  };

  return (
    <section className="border-b border-[var(--border)] bg-[var(--wash)] px-4 md:px-8 py-4">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-baseline justify-between gap-4">
          <div>
            <p className="font-mono text-[10px] uppercase tracking-[.18em] text-[var(--text-muted)]">Generate from project</p>
            <p className="mt-1 text-[12px] text-[var(--text-secondary)]">AI researches only the selected project, verifies each claim, and renders real Word footnotes.</p>
          </div>
          <span className="font-mono text-[9px] uppercase text-[var(--text-muted)]">quality demo</span>
        </div>
        <form onSubmit={submit} className="mt-3 grid md:grid-cols-[1fr_130px_130px_auto] gap-2">
          <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="Report topic or issue" className="px-3 py-2 bg-[var(--bg-primary)] border border-[var(--border)] text-[12px] text-[var(--text-primary)] rounded-[2px]" />
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} aria-label="Report date from" className="px-2 py-2 bg-[var(--bg-primary)] border border-[var(--border)] text-[11px] text-[var(--text-primary)]" />
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} aria-label="Report date to" className="px-2 py-2 bg-[var(--bg-primary)] border border-[var(--border)] text-[11px] text-[var(--text-primary)]" />
          <button disabled={!canEdit || submitting || !topic.trim()} className="px-4 py-2 bg-[var(--accent)] text-[var(--accent-ink)] font-mono text-[10px] uppercase tracking-[.12em] disabled:opacity-40">Generate</button>
          <input value={parties} onChange={(e) => setParties(e.target.value)} placeholder="Parties, comma separated" className="md:col-span-2 px-3 py-2 bg-[var(--bg-primary)] border border-[var(--border)] text-[11px] text-[var(--text-primary)]" />
          {module === 'chronology' ? (
            <span className="flex items-center px-2 text-[10px] text-[var(--text-muted)]">Number assigned automatically</span>
          ) : (
            <select value={issueStatus} onChange={(e) => setIssueStatus(e.target.value as 'Draft' | 'Issue')} className="bg-[var(--bg-primary)] border border-[var(--border)] px-2 text-[11px] text-[var(--text-primary)]"><option>Draft</option><option>Issue</option></select>
          )}
        </form>
        {error && <p className="mt-2 text-[11px] text-[var(--danger)]">{error}</p>}
        {module === 'forensic' && toolkitArtifacts.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-3 text-[10px] text-[var(--text-secondary)]">
            <span className="font-mono uppercase text-[var(--text-muted)]">Toolkit packages</span>
            {toolkitArtifacts.map((artifact) => (
              <label key={artifact.artifact_id} className="flex items-center gap-1">
                <input type="checkbox" checked={selectedToolkit.includes(artifact.artifact_id)} onChange={(event) => setSelectedToolkit((current) => event.target.checked ? [...current, artifact.artifact_id] : current.filter((id) => id !== artifact.artifact_id))} />
                {artifact.title}
              </label>
            ))}
          </div>
        )}
        {jobs.length > 0 && (
          <div className="mt-4 grid gap-2">
            {jobs.map((job) => {
              const evidence = Array.isArray(job.result?.evidence) ? job.result.evidence as Array<Record<string, unknown>> : [];
              const entries = Array.isArray(job.result?.entries) ? job.result.entries as Array<Record<string, unknown>> : [];
              return (
                <div key={job.job_id} className="border-t border-[var(--border)] pt-2 text-[11px]">
                  <div className="flex items-center gap-3">
                    <span className="flex-1 truncate text-[var(--text-primary)]">{job.title}</span>
                    <span className="font-mono uppercase text-[var(--text-muted)]">{job.stage} · {Math.round(job.progress * 100)}%</span>
                    {job.status === 'ready' && <button type="button" onClick={() => openReview(job)} className="text-[var(--text-secondary)]">Review</button>}
                    {job.status === 'ready' && <button type="button" onClick={() => void downloadReport(job)} className="text-[var(--accent)]">Word ↓</button>}
                    {job.status === 'failed' && <span title={job.error ?? ''} className="text-[var(--danger)]">failed</span>}
                    {job.status === 'credit_balance_exhausted' && (
                      <span title="Kredi bakiyesi tükendi" className="text-[var(--danger)]">
                        kredi tükendi
                      </span>
                    )}
                  </div>
                  {reviewing === job.job_id && job.status === 'ready' && (
                    <div className="mt-3 border border-[var(--border)] bg-[var(--bg-primary)] p-3 max-h-[440px] overflow-auto">
                      {module === 'chronology' ? entries.map((entry, index) => (
                        <div key={index} className="mb-3">
                          <p className="font-mono text-[10px] text-[var(--text-muted)]">6.{job.sequence_number}.{index + 1} · {String(entry.event_date ?? 'Date not established')}</p>
                          {(Array.isArray(entry.claims) ? entry.claims as Array<Record<string, unknown>> : []).map((claim, claimIndex) => (
                            <p key={claimIndex} className="mt-1 text-[var(--text-primary)]">{String(claim.text ?? '')} <span className="text-[var(--accent)]">[{(claim.source_ids as string[] ?? []).join(', ')}]</span></p>
                          ))}
                        </div>
                      )) : Object.entries(draftSections).map(([name, claims]) => (
                        <div key={name} className="mb-4">
                          <p className="font-mono text-[10px] uppercase tracking-[.1em] text-[var(--text-muted)]">{name}</p>
                          {claims.map((claim, claimIndex) => (
                            <textarea key={claimIndex} value={String(claim.text ?? '')}
                              onChange={(event) => setDraftSections((current) => ({ ...current, [name]: current[name].map((item, index) => index === claimIndex ? { ...item, text: event.target.value } : item) }))}
                              className="mt-1 w-full min-h-16 border border-[var(--border)] bg-[var(--wash)] p-2 text-[11px] text-[var(--text-primary)]" />
                          ))}
                        </div>
                      ))}
                      <p className="font-mono text-[10px] uppercase text-[var(--text-muted)]">Sources · {evidence.length}</p>
                      {evidence.slice(0, 30).map((source, index) => <p key={index} className="mt-1 text-[10px] text-[var(--text-secondary)]">{String(source.source_id)} · {String(source.file_name)} {source.page ? `· p.${source.page}` : ''}</p>)}
                      {module === 'forensic' && canEdit && <div className="mt-3 flex gap-2"><button type="button" onClick={() => void saveReview(job, false)} className="border border-[var(--border)] px-3 py-1">Save Draft</button><button type="button" onClick={() => void saveReview(job, true)} className="bg-[var(--accent)] px-3 py-1 text-[var(--accent-ink)]">Validate & Issue</button></div>}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
