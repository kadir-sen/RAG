import { useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import FileUploadArea from '../components/files/FileUploadArea';
import { archiveProject, createProject, renameProject } from '../api/projectApi';
import { deleteFile, getIndexingStatus, listFiles, retryFileIndexing, uploadFile } from '../api/fileApi';
import type { FileInfo, IndexingStatus } from '../types/api';
import { useProjectStore } from '../stores/projectStore';
import QueryHistory from '../components/projects/QueryHistory';
import { useAuthStore } from '../stores/authStore';
import ModuleTile from '../components/modules/ModuleTile';
import { ChatbotMark, ChronologyMark, ReportsMark } from '../components/modules/ModuleMarks';
import { isAxiosError } from 'axios';

const PAGE_SIZE = 50;

function duration(seconds: number | null) {
  if (seconds == null) return 'calibrating';
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.ceil(seconds / 60);
  return minutes < 60 ? `${minutes}m` : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

function typeLabel(fileType: string) {
  if (fileType === 'email') return 'Mail';
  if (fileType === 'data') return 'Spreadsheet';
  return 'Document';
}

function storage(value: number) {
  return `${(value / 1_000_000_000).toFixed(2)} GB`;
}

export default function ProjectsPage() {
  const queryClient = useQueryClient();
  const projects = useProjectStore((s) => s.projects);
  const selectedProjectId = useProjectStore((s) => s.selectedProjectId);
  const loading = useProjectStore((s) => s.loading);
  const load = useProjectStore((s) => s.load);
  const select = useProjectStore((s) => s.select);
  const [name, setName] = useState('');
  const [creating, setCreating] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [jobs, setJobs] = useState<IndexingStatus[]>([]);
  const [renameValue, setRenameValue] = useState('');
  const [fileSearch, setFileSearch] = useState('');
  const [fileType, setFileType] = useState<'all' | 'document' | 'email' | 'data'>('all');
  const [filePage, setFilePage] = useState(1);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState('');
  const user = useAuthStore((s) => s.user);
  const refreshMe = useAuthStore((s) => s.refreshMe);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!selectedProjectId) { setJobs([]); return; }
    let live = true;
    const poll = async () => {
      try {
        const next = await getIndexingStatus();
        if (live) setJobs(next);
        await load();
      } catch { /* project may be changing */ }
    };
    void poll();
    const timer = window.setInterval(poll, 2500);
    return () => { live = false; window.clearInterval(timer); };
  }, [selectedProjectId, load]);

  const current = projects.find((p) => p.project_id === selectedProjectId) ?? null;
  const filesQuery = useQuery({
    queryKey: ['files', selectedProjectId],
    queryFn: listFiles,
    enabled: Boolean(selectedProjectId),
    staleTime: 5_000,
  });

  useEffect(() => {
    setRenameValue(current?.name ?? '');
    setFileSearch('');
    setFileType('all');
    setFilePage(1);
    setActionError('');
  }, [current?.project_id, current?.name]);

  const active = useMemo(
    () => jobs.filter((j) => !['ready', 'failed', 'credit_balance_exhausted'].includes(j.status)),
    [jobs],
  );
  const canOpen = Boolean(current?.stats.report_ready) && active.length === 0;
  const canOpenForensic = Boolean(current) && active.length === 0;
  const canEditFiles = Boolean(current && current.role !== 'viewer');
  const canRename = Boolean(current && ['owner', 'admin'].includes(current.role));

  const filteredFiles = useMemo(() => {
    const needle = fileSearch.trim().toLocaleLowerCase();
    return (filesQuery.data ?? []).filter((file) =>
      (fileType === 'all' || file.file_type === fileType)
      && (!needle || file.name.toLocaleLowerCase().includes(needle))
    );
  }, [fileSearch, fileType, filesQuery.data]);
  const pageCount = Math.max(1, Math.ceil(filteredFiles.length / PAGE_SIZE));
  const visibleFiles = filteredFiles.slice((filePage - 1) * PAGE_SIZE, filePage * PAGE_SIZE);

  useEffect(() => {
    if (filePage > pageCount) setFilePage(pageCount);
  }, [filePage, pageCount]);

  const addProject = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    setActionError('');
    try {
      const project = await createProject(name.trim());
      await load();
      select(project.project_id);
      setName('');
    } catch {
      setActionError('The project could not be created.');
    } finally { setCreating(false); }
  };

  const addFiles = async (files: File[]) => {
    if (!selectedProjectId || !canEditFiles) return;
    setUploading(true);
    setActionError('');
    // Two uploads at once matches the 8 GB server's initial ingestion limit.
    let cursor = 0;
    const worker = async () => {
      while (cursor < files.length) {
        const file = files[cursor++];
        await uploadFile(file);
      }
    };
    try {
      await Promise.all([worker(), worker()]);
      await load();
      setJobs(await getIndexingStatus());
      await queryClient.invalidateQueries({ queryKey: ['files', selectedProjectId] });
      await queryClient.invalidateQueries({ queryKey: ['library', selectedProjectId] });
    } catch (error) {
      if (isAxiosError(error) && error.response?.status === 413
          && error.response.data?.error === 'storage_quota_exceeded') {
        const used = Number(error.response.data.storage_used_bytes ?? user?.storage_used_bytes ?? 0);
        const limit = Number(error.response.data.storage_limit_bytes ?? user?.storage_limit_bytes ?? 30_000_000_000);
        setActionError(`The upload exceeds your source-file allowance: ${storage(used)} used of ${storage(limit)}. Delete an existing source file or contact an administrator.`);
      } else {
        setActionError('One or more files could not be uploaded. Completed uploads remain queued.');
      }
    } finally {
      await refreshMe();
      setUploading(false);
    }
  };

  const saveName = async () => {
    const nextName = renameValue.trim();
    if (!current || !nextName || nextName === current.name) return;
    setActionError('');
    try {
      await renameProject(current.project_id, nextName);
      await load();
    } catch {
      setActionError('The project name could not be changed.');
    }
  };

  const removeFile = async (file: FileInfo) => {
    if (!current || !canEditFiles) return;
    const confirmed = window.confirm(
      `Delete “${file.name}” from “${current.name}”?\n\nThis removes the source file and its OCR, chunks, vectors, tables and extracted evidence. This action cannot be undone.`,
    );
    if (!confirmed) return;
    setDeletingId(file.id);
    setActionError('');
    try {
      await deleteFile(file.id);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['files', selectedProjectId] }),
        queryClient.invalidateQueries({ queryKey: ['library', selectedProjectId] }),
        queryClient.invalidateQueries({ queryKey: ['chronology', selectedProjectId] }),
        load(),
        refreshMe(),
      ]);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Deletion failed';
      setActionError(`“${file.name}” was not deleted. ${message}`);
    } finally {
      setDeletingId(null);
    }
  };

  const retryJob = async (fileId: string) => {
    setActionError('');
    try {
      await retryFileIndexing(fileId);
      setJobs(await getIndexingStatus());
    } catch {
      setActionError('The job could not be restarted. Check the credit balance and try again.');
    }
  };

  const archiveCurrent = async () => {
    if (!current || !window.confirm(`Archive project “${current.name}”? Documents are retained.`)) return;
    setActionError('');
    try {
      await archiveProject(current.project_id);
      select(null);
      await load();
    } catch {
      setActionError('The project could not be archived.');
    }
  };

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-7xl mx-auto px-3 sm:px-4 md:px-6 py-3 md:py-10">
        <header className="mb-4 flex flex-col gap-4 md:mb-7 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-muted)]">Project management</p>
            <h1 className="mt-2 text-2xl font-semibold text-[var(--text-primary)]">Projects and source records</h1>
            <p className="mt-2 text-[13px] text-[var(--text-secondary)]">Each module can only see the documents in the active project shown in the top-left selector.</p>
          </div>
        </header>

        {actionError && <div role="alert" className="mb-5 border border-[var(--danger)] bg-[var(--bg-primary)] px-4 py-3 text-[11px] text-[var(--danger)]">{actionError}</div>}

        <div className="grid xl:grid-cols-[300px_minmax(0,1fr)] gap-5 md:gap-6">
          <aside className="space-y-4 md:grid md:grid-cols-2 md:gap-5 md:space-y-0 xl:block xl:space-y-5">
            <section className="border border-[var(--border)] bg-[var(--wash)] p-4 md:hidden" aria-labelledby="mobile-project-controls">
              <h2 id="mobile-project-controls" className="font-mono text-[10px] uppercase tracking-[.16em] text-[var(--text-muted)]">Project controls</h2>
              <label htmlFor="mobile-project-select" className="mt-3 block font-mono text-[9px] uppercase tracking-[.12em] text-[var(--text-secondary)]">Active project</label>
              <select
                id="mobile-project-select"
                value={selectedProjectId ?? ''}
                onChange={(event) => select(event.target.value || null)}
                className="mt-1 min-h-11 w-full border border-[var(--border)] bg-[var(--bg-primary)] px-3 text-base text-[var(--text-primary)]"
              >
                <option value="">Select a project</option>
                {projects.map((project) => <option key={project.project_id} value={project.project_id}>{project.name}</option>)}
              </select>
              <details className="mt-3 border-t border-[var(--border)] pt-3">
                <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between font-mono text-[10px] uppercase tracking-[.12em] text-[var(--text-primary)]">
                  Create new project <span aria-hidden="true">＋</span>
                </summary>
                <form onSubmit={addProject} className="pt-2">
                  <label htmlFor="new-project-name-mobile" className="sr-only">Project name</label>
                  <input id="new-project-name-mobile" value={name} onChange={(e) => setName(e.target.value)} placeholder="Project name" className="min-h-11 w-full border border-[var(--border)] bg-[var(--bg-primary)] px-3 text-base text-[var(--text-primary)]" />
                  <button disabled={creating || !name.trim()} className="mt-2 min-h-11 w-full border border-[var(--border)] px-3 text-[11px] text-[var(--text-primary)] hover:border-[var(--ink)] disabled:opacity-40">{creating ? 'Creating…' : 'Create project'}</button>
                </form>
              </details>
            </section>

            <section className="hidden border border-[var(--border)] bg-[var(--wash)] p-4 md:block">
              <h2 className="font-mono text-[10px] uppercase tracking-[.16em] text-[var(--text-muted)]">Your projects</h2>
              <div className="mt-3 space-y-2">
                {projects.map((project) => (
                  <button
                    type="button"
                    key={project.project_id}
                    onClick={() => select(project.project_id)}
                    aria-pressed={selectedProjectId === project.project_id}
                    className={`w-full text-left border p-3 bg-[var(--bg-primary)] transition-colors ${selectedProjectId === project.project_id ? 'border-[var(--accent)] shadow-[inset_3px_0_0_var(--accent)]' : 'border-[var(--border)] hover:border-[var(--ink)]'}`}
                  >
                    <div className="flex justify-between gap-3">
                      <span className="truncate text-[13px] font-semibold text-[var(--text-primary)]">{project.name}</span>
                      <span className="font-mono text-[8px] uppercase text-[var(--text-muted)]">{project.role}</span>
                    </div>
                    <p className="mt-2 font-mono text-[9px] text-[var(--text-secondary)]">{project.stats.files.document} docs · {project.stats.files.email} mail · {project.stats.files.data} sheets · {project.stats.files.programme ?? 0} XER</p>
                    <p className="mt-1 text-[10px] text-[var(--text-muted)]">{project.stats.report_ready ? 'Ready for reports' : `${project.stats.queued + project.stats.processing} remaining · ETA ${duration(project.stats.eta_seconds)}`}</p>
                    <p className="mt-1 font-mono text-[8px] uppercase text-[var(--text-muted)]">Vectors · {project.stats.vector.status} · {project.stats.vector.point_count.toLocaleString()}</p>
                  </button>
                ))}
                {!loading && projects.length === 0 && <p className="py-5 text-[11px] text-[var(--text-secondary)]">Create the first project to begin.</p>}
              </div>
            </section>

            {user?.plan_type === 'demo' && (
              <section className="border border-[var(--border)] bg-[var(--wash)] p-4 md:col-span-2 xl:col-auto">
                <div className="flex items-center justify-between gap-3">
                  <h2 className="font-mono text-[10px] uppercase tracking-[.16em] text-[var(--text-muted)]">Account capacity</h2>
                  <span className="font-mono text-[10px] text-[var(--text-secondary)]">{user.storage_percent_used.toFixed(1)}% used</span>
                </div>
                <div className="mt-3 h-1.5 bg-[var(--wash-firm)]">
                  <div className="h-full bg-[var(--accent)]" style={{ width: `${Math.min(100, user.storage_percent_used)}%` }} />
                </div>
                <p className="mt-2 font-mono text-[9px] text-[var(--text-muted)]">{storage(user.storage_used_bytes)} / {storage(user.storage_limit_bytes)} source files</p>
                <p className="mt-1 hidden text-[10px] text-[var(--text-secondary)] sm:block">30 GB is shared across all projects. OCR, vectors and generated reports do not consume this allowance.</p>
                <p className="mt-1 font-mono text-[9px] text-[var(--text-muted)]">{user.credits_remaining.toFixed(2)} / {user.credits_total.toFixed(2)} credits remaining</p>
              </section>
            )}

            <section className="hidden border border-[var(--border)] bg-[var(--wash)] p-4 md:block">
              <h2 className="font-mono text-[10px] uppercase tracking-[.16em] text-[var(--text-muted)]">New project</h2>
              <form onSubmit={addProject} className="mt-3">
                <label htmlFor="new-project-name" className="sr-only">Project name</label>
                <input id="new-project-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Project name" className="min-h-11 w-full px-3 py-2 bg-[var(--bg-primary)] border border-[var(--border)] text-base md:text-sm text-[var(--text-primary)] rounded-[2px]" />
                <button disabled={creating || !name.trim()} className="mt-3 min-h-11 w-full px-3 py-2 border border-[var(--border)] text-[11px] text-[var(--text-primary)] hover:border-[var(--ink)] disabled:opacity-40">{creating ? 'Creating…' : 'Create project'}</button>
              </form>
            </section>
          </aside>

          <main className="min-w-0">
            {!current ? (
              <div className="border border-[var(--border)] bg-[var(--wash)] p-10 text-center">
                <p className="font-mono text-[10px] uppercase tracking-[.16em] text-[var(--text-muted)]">No active project</p>
                <p className="mt-3 text-[13px] text-[var(--text-secondary)]">Select a project on the left to manage its name, files and processing queue.</p>
              </div>
            ) : (
              <>
                <section className="flex flex-col border border-[var(--border)] bg-[var(--wash)]">
                  <div className="p-4 border-b border-[var(--border)] flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                    <div>
                      <p className="font-mono text-[9px] uppercase tracking-[.15em] text-[var(--text-muted)]">Selected project</p>
                      <div className="mt-1 flex flex-wrap items-center gap-2">
                        <h2 className="min-w-0 break-words text-[17px] font-semibold text-[var(--text-primary)]">{current.name}</h2>
                        <span className="border border-[var(--border)] px-1.5 py-0.5 font-mono text-[8px] uppercase text-[var(--text-muted)]">{current.stats.report_ready ? 'ready' : 'processing'}</span>
                        <span className="border border-[var(--border)] px-1.5 py-0.5 font-mono text-[8px] uppercase text-[var(--text-muted)]">vector {current.stats.vector.status}</span>
                      </div>
                      <p className="mt-1 text-[11px] text-[var(--text-muted)]">Only this record is available in Chatbot, Chronology and Forensic Reports.</p>
                    </div>
                    {canRename && (
                      <div className="flex min-w-0 flex-col gap-2 sm:flex-row md:w-[360px]">
                        <label htmlFor="project-name" className="sr-only">Rename project</label>
                        <input id="project-name" value={renameValue} onChange={(event) => setRenameValue(event.target.value)} className="min-h-11 min-w-0 flex-1 bg-[var(--bg-primary)] border border-[var(--border)] px-3 py-2 text-base md:text-[11px] text-[var(--text-primary)]" />
                        <button type="button" disabled={!renameValue.trim() || renameValue.trim() === current.name} onClick={() => void saveName()} className="min-h-11 border border-[var(--border)] px-3 font-mono text-[9px] uppercase disabled:opacity-40">Save name</button>
                      </div>
                    )}
                  </div>

                  <div data-testid="project-metrics" className="order-3 grid grid-cols-2 border-b border-[var(--border)] md:order-2 md:grid-cols-4 lg:grid-cols-8">
                    {[
                      ['Documents', current.stats.files.document],
                      ['Mail', current.stats.files.email],
                      ['Spreadsheets', current.stats.files.data],
                      ['Programmes', current.stats.files.programme ?? 0],
                      ['Vector points', current.stats.vector.point_count],
                      ['Remaining', current.stats.queued + current.stats.processing],
                      ['Model tokens', current.usage.prompt_tokens + current.usage.completion_tokens],
                      ['Credits used', current.usage.credits_used.toFixed(2)],
                    ].map(([label, value]) => (
                      <div key={label} className="min-w-0 border-b border-r border-[var(--border)] p-3 last:border-r-0 md:p-4 lg:border-b-0">
                        <p className="font-mono text-[9px] uppercase text-[var(--text-muted)]">{label}</p>
                        <p className="mt-1 text-xl font-semibold text-[var(--text-primary)]">{Number(value).toLocaleString()}</p>
                      </div>
                    ))}
                  </div>

                  <div data-testid="project-modules" className="order-2 border-b border-[var(--border)] bg-[var(--bg-primary)] p-4 md:order-3 md:p-7">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                      <div><p className="font-mono text-[9px] uppercase tracking-[.16em] text-[var(--text-muted)]">Start with a module</p><h3 className="mt-1 text-lg font-semibold text-[var(--text-primary)]">Work in {current.name}</h3></div>
                      {!canOpen && <p className="font-mono text-[9px] text-[var(--amber)]">{active.length || current.stats.queued + current.stats.processing} remaining · ETA {duration(current.stats.eta_seconds)}</p>}
                    </div>
                    <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3 md:gap-7">
                      <ModuleTile index="01" name="Chatbot" role="Ask and investigate" blurb={`${current.name} · Search documents, correspondence and project data.`} mark={<ChatbotMark className="h-full w-full" />} to={canOpen ? '/chat' : undefined} status={canOpen ? 'live' : 'soon'} statusLabel={canOpen ? 'Ready' : 'Processing'} />
                      <ModuleTile index="02" name="Chronology" role="Build an evidence timeline" blurb={`${current.name} · Generate a sourced English chronology and Word report.`} mark={<ChronologyMark className="h-full w-full" />} to={canOpen ? '/chronology' : undefined} status={canOpen ? 'live' : 'soon'} statusLabel={canOpen ? 'Ready' : 'Processing'} />
                      <ModuleTile index="03" name="Forensic Reports" role="Native programme analysis" blurb={`${current.name} · Upload XER programmes and run DCMA, critical-path and delay analyses inside COAir.`} mark={<ReportsMark className="h-full w-full" />} to={canOpenForensic ? '/forensic' : undefined} status={canOpenForensic ? 'live' : 'soon'} statusLabel={canOpenForensic ? 'Ready' : 'Processing'} />
                    </div>
                  </div>

                  <div className="order-4 p-3 border-b border-[var(--border)]">
                    {canEditFiles ? <FileUploadArea onUpload={addFiles} isUploading={uploading} storageUsedBytes={user?.storage_used_bytes} storageLimitBytes={user?.storage_limit_bytes} /> : <p className="p-3 text-[11px] text-[var(--text-muted)]">Viewer access · uploads and deletion are disabled.</p>}
                  </div>

                  {jobs.length > 0 && (
                    <div className="order-5 max-h-52 overflow-y-auto border-b border-[var(--border)]">
                      {jobs.map((job) => (
                        <div key={job.file_id} className="px-4 py-3 border-b border-[var(--border)] last:border-b-0 bg-[var(--bg-primary)]">
                          <div className="flex justify-between gap-4 text-[11px]"><span className="truncate text-[var(--text-primary)]">{job.filename}</span><span className="font-mono uppercase text-[var(--text-muted)]">{job.status}</span></div>
                          <div className="mt-2 h-1 bg-[var(--wash-firm)]"><div className="h-full bg-[var(--accent)]" style={{ width: `${Math.round(job.progress * 100)}%` }} /></div>
                          {job.error && <p className="mt-1 text-[10px] text-[var(--danger)]">{job.error}</p>}
                          {job.status === 'credit_balance_exhausted' && canEditFiles && (
                            <button type="button" onClick={() => void retryJob(job.file_id)} className="mt-2 border border-[var(--border)] px-2 py-1 font-mono text-[9px] uppercase text-[var(--text-secondary)]">
                              Retry after top-up
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </section>

                <section className="mt-6 border border-[var(--border)] bg-[var(--wash)]">
                  <div className="p-4 border-b border-[var(--border)] flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                    <div>
                      <h2 className="text-[14px] font-semibold text-[var(--text-primary)]">Project documents</h2>
                      <p className="mt-1 text-[10px] text-[var(--text-muted)]">{filteredFiles.length.toLocaleString()} of {(filesQuery.data ?? []).length.toLocaleString()} files in {current.name}</p>
                    </div>
                    <div className="flex flex-col sm:flex-row gap-2">
                      <label htmlFor="project-file-search" className="sr-only">Search project files</label>
                      <input id="project-file-search" type="search" value={fileSearch} onChange={(event) => { setFileSearch(event.target.value); setFilePage(1); }} placeholder="Search file name" className="min-h-11 w-full sm:w-60 bg-[var(--bg-primary)] border border-[var(--border)] px-3 py-2 text-base md:text-[11px] text-[var(--text-primary)]" />
                      <label htmlFor="project-file-type" className="sr-only">Filter by file type</label>
                      <select id="project-file-type" value={fileType} onChange={(event) => { setFileType(event.target.value as typeof fileType); setFilePage(1); }} className="min-h-11 bg-[var(--bg-primary)] border border-[var(--border)] px-3 py-2 text-base md:text-[11px] text-[var(--text-primary)]">
                        <option value="all">All file types</option>
                        <option value="document">Documents</option>
                        <option value="email">Mail</option>
                        <option value="data">Spreadsheets</option>
                      </select>
                    </div>
                  </div>

                  <div className="min-h-32">
                    {filesQuery.isLoading ? (
                      <p className="p-5 text-[11px] text-[var(--text-muted)]">Loading project files…</p>
                    ) : visibleFiles.length === 0 ? (
                      <p className="p-5 text-[11px] text-[var(--text-muted)]">No files match this view.</p>
                    ) : visibleFiles.map((file) => (
                      <div key={file.id} className="group flex min-h-14 items-center gap-3 border-b border-[var(--border)] last:border-b-0 bg-[var(--bg-primary)] px-3 py-2 md:px-4 md:py-3">
                        <span className="hidden w-20 shrink-0 font-mono text-[8px] uppercase tracking-[.1em] text-[var(--text-muted)] md:block">{typeLabel(file.file_type)}</span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[12px] text-[var(--text-primary)] md:text-[11px]" title={file.name}>{file.name}</span>
                          <span className="mt-1 flex gap-2 font-mono text-[8px] uppercase tracking-[.08em] text-[var(--text-muted)] md:hidden">
                            <span>{typeLabel(file.file_type)}</span><span aria-hidden="true">·</span><span>{file.status ?? 'ready'}</span>
                          </span>
                        </span>
                        <span className="hidden md:block font-mono text-[9px] uppercase text-[var(--text-muted)]">{file.status ?? 'ready'}</span>
                        {canEditFiles && (
                          <button type="button" disabled={deletingId === file.id} onClick={() => void removeFile(file)} aria-label={`Delete ${file.name}`} className="min-h-11 min-w-11 shrink-0 px-2 py-1 font-mono text-[9px] uppercase text-[var(--text-muted)] hover:text-[var(--danger)] disabled:opacity-40">{deletingId === file.id ? 'Deleting…' : 'Delete'}</button>
                        )}
                      </div>
                    ))}
                  </div>

                  {filteredFiles.length > PAGE_SIZE && (
                    <div className="flex items-center justify-between border-t border-[var(--border)] px-3 py-2 md:px-4 md:py-3">
                      <button type="button" disabled={filePage === 1} onClick={() => setFilePage((page) => Math.max(1, page - 1))} className="min-h-11 px-1 font-mono text-[9px] uppercase text-[var(--text-secondary)] disabled:opacity-30">← Previous</button>
                      <span className="font-mono text-[9px] text-[var(--text-muted)]">Page {filePage.toLocaleString()} / {pageCount.toLocaleString()}</span>
                      <button type="button" disabled={filePage === pageCount} onClick={() => setFilePage((page) => Math.min(pageCount, page + 1))} className="min-h-11 px-1 font-mono text-[9px] uppercase text-[var(--text-secondary)] disabled:opacity-30">Next →</button>
                    </div>
                  )}
                </section>

                <QueryHistory projectId={current.project_id} />

                {canRename && (
                  <section className="mt-6 flex flex-col gap-4 border border-[var(--border)] bg-[var(--wash)] p-4 sm:flex-row sm:items-center sm:justify-between">
                    <div><p className="font-mono text-[9px] uppercase text-[var(--text-muted)]">Project lifecycle</p><p className="mt-1 text-[10px] text-[var(--text-secondary)]">Archiving hides the project but retains its documents and evidence.</p></div>
                    <button type="button" onClick={() => void archiveCurrent()} className="min-h-11 w-full shrink-0 border border-[var(--danger)] px-3 py-2 font-mono text-[9px] uppercase text-[var(--danger)] sm:w-auto">Archive project</button>
                  </section>
                )}
              </>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
