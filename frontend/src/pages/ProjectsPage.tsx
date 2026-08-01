import { useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import FileUploadArea from '../components/files/FileUploadArea';
import { archiveProject, createProject, renameProject } from '../api/projectApi';
import { deleteFile, getIndexingStatus, listFiles, uploadFile } from '../api/fileApi';
import type { FileInfo, IndexingStatus } from '../types/api';
import { useProjectStore } from '../stores/projectStore';
import QueryHistory from '../components/projects/QueryHistory';

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

export default function ProjectsPage() {
  const navigate = useNavigate();
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

  const active = useMemo(() => jobs.filter((j) => !['ready', 'failed'].includes(j.status)), [jobs]);
  const canOpen = Boolean(current?.stats.report_ready) && active.length === 0;
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
    } catch {
      setActionError('One or more files could not be uploaded. Completed uploads remain queued.');
    } finally { setUploading(false); }
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
      ]);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Deletion failed';
      setActionError(`“${file.name}” was not deleted. ${message}`);
    } finally {
      setDeletingId(null);
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
      <div className="max-w-7xl mx-auto px-4 md:px-6 py-8 md:py-10">
        <header className="mb-7 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-muted)]">Project management</p>
            <h1 className="mt-2 text-2xl font-semibold text-[var(--text-primary)]">Projects and source records</h1>
            <p className="mt-2 text-[13px] text-[var(--text-secondary)]">Each module can only see the documents in the active project shown in the top-left selector.</p>
          </div>
          {current && (
            <div className="flex items-center gap-3 border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2">
              <span className={`h-2 w-2 rounded-full ${current.stats.report_ready ? 'bg-[var(--green)]' : 'bg-[var(--amber)]'}`} />
              <span className="text-[11px] text-[var(--text-secondary)]"><strong className="text-[var(--text-primary)]">{current.name}</strong> is active</span>
              <button type="button" disabled={!canOpen} onClick={() => navigate('/')} className="ml-2 px-3 py-1.5 bg-[var(--accent)] text-[var(--accent-ink)] font-mono text-[9px] uppercase tracking-[.14em] disabled:opacity-40">{canOpen ? 'Open modules →' : 'Processing…'}</button>
            </div>
          )}
        </header>

        {actionError && <div role="alert" className="mb-5 border border-[var(--danger)] bg-[var(--bg-primary)] px-4 py-3 text-[11px] text-[var(--danger)]">{actionError}</div>}

        <div className="grid xl:grid-cols-[300px_minmax(0,1fr)] gap-6">
          <aside className="space-y-5">
            <section className="border border-[var(--border)] bg-[var(--wash)] p-4">
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
                    <p className="mt-2 font-mono text-[9px] text-[var(--text-secondary)]">{project.stats.files.document} docs · {project.stats.files.email} mail · {project.stats.files.data} sheets</p>
                    <p className="mt-1 text-[10px] text-[var(--text-muted)]">{project.stats.report_ready ? 'Ready for reports' : `${project.stats.queued + project.stats.processing} remaining · ETA ${duration(project.stats.eta_seconds)}`}</p>
                    <p className="mt-1 font-mono text-[8px] uppercase text-[var(--text-muted)]">Vectors · {project.stats.vector.status} · {project.stats.vector.point_count.toLocaleString()}</p>
                  </button>
                ))}
                {!loading && projects.length === 0 && <p className="py-5 text-[11px] text-[var(--text-secondary)]">Create the first project to begin.</p>}
              </div>
            </section>

            <section className="border border-[var(--border)] bg-[var(--wash)] p-4">
              <h2 className="font-mono text-[10px] uppercase tracking-[.16em] text-[var(--text-muted)]">New project</h2>
              <form onSubmit={addProject} className="mt-3">
                <label htmlFor="new-project-name" className="sr-only">Project name</label>
                <input id="new-project-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Project name" className="w-full px-3 py-2 bg-[var(--bg-primary)] border border-[var(--border)] text-sm text-[var(--text-primary)] rounded-[2px]" />
                <button disabled={creating || !name.trim()} className="mt-3 w-full px-3 py-2 border border-[var(--border)] text-[11px] text-[var(--text-primary)] hover:border-[var(--ink)] disabled:opacity-40">{creating ? 'Creating…' : 'Create project'}</button>
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
                <section className="border border-[var(--border)] bg-[var(--wash)]">
                  <div className="p-4 border-b border-[var(--border)] flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                    <div>
                      <p className="font-mono text-[9px] uppercase tracking-[.15em] text-[var(--text-muted)]">Selected project</p>
                      <div className="mt-1 flex items-center gap-2">
                        <h2 className="text-[17px] font-semibold text-[var(--text-primary)]">{current.name}</h2>
                        <span className="border border-[var(--border)] px-1.5 py-0.5 font-mono text-[8px] uppercase text-[var(--text-muted)]">{current.stats.report_ready ? 'ready' : 'processing'}</span>
                        <span className="border border-[var(--border)] px-1.5 py-0.5 font-mono text-[8px] uppercase text-[var(--text-muted)]">vector {current.stats.vector.status}</span>
                      </div>
                      <p className="mt-1 text-[11px] text-[var(--text-muted)]">Only this record is available in Chatbot, Chronology and Forensic Reports.</p>
                    </div>
                    {canRename && (
                      <div className="flex min-w-0 md:w-[360px] gap-2">
                        <label htmlFor="project-name" className="sr-only">Rename project</label>
                        <input id="project-name" value={renameValue} onChange={(event) => setRenameValue(event.target.value)} className="min-w-0 flex-1 bg-[var(--bg-primary)] border border-[var(--border)] px-3 py-2 text-[11px] text-[var(--text-primary)]" />
                        <button type="button" disabled={!renameValue.trim() || renameValue.trim() === current.name} onClick={() => void saveName()} className="border border-[var(--border)] px-3 font-mono text-[9px] uppercase disabled:opacity-40">Save name</button>
                      </div>
                    )}
                  </div>

                  <div className="grid sm:grid-cols-5 border-b border-[var(--border)]">
                    {[
                      ['Documents', current.stats.files.document],
                      ['Mail', current.stats.files.email],
                      ['Spreadsheets', current.stats.files.data],
                      ['Vector points', current.stats.vector.point_count],
                      ['Remaining', current.stats.queued + current.stats.processing],
                    ].map(([label, value]) => (
                      <div key={label} className="p-4 border-b sm:border-b-0 sm:border-r last:border-r-0 border-[var(--border)]">
                        <p className="font-mono text-[9px] uppercase text-[var(--text-muted)]">{label}</p>
                        <p className="mt-1 text-xl font-semibold text-[var(--text-primary)]">{Number(value).toLocaleString()}</p>
                      </div>
                    ))}
                  </div>

                  <div className="p-3 border-b border-[var(--border)]">
                    {canEditFiles ? <FileUploadArea onUpload={addFiles} isUploading={uploading} /> : <p className="p-3 text-[11px] text-[var(--text-muted)]">Viewer access · uploads and deletion are disabled.</p>}
                  </div>

                  {jobs.length > 0 && (
                    <div className="max-h-52 overflow-y-auto border-b border-[var(--border)]">
                      {jobs.map((job) => (
                        <div key={job.file_id} className="px-4 py-3 border-b border-[var(--border)] last:border-b-0 bg-[var(--bg-primary)]">
                          <div className="flex justify-between gap-4 text-[11px]"><span className="truncate text-[var(--text-primary)]">{job.filename}</span><span className="font-mono uppercase text-[var(--text-muted)]">{job.status}</span></div>
                          <div className="mt-2 h-1 bg-[var(--wash-firm)]"><div className="h-full bg-[var(--accent)]" style={{ width: `${Math.round(job.progress * 100)}%` }} /></div>
                          {job.error && <p className="mt-1 text-[10px] text-[var(--danger)]">{job.error}</p>}
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
                      <input id="project-file-search" type="search" value={fileSearch} onChange={(event) => { setFileSearch(event.target.value); setFilePage(1); }} placeholder="Search file name" className="w-full sm:w-60 bg-[var(--bg-primary)] border border-[var(--border)] px-3 py-2 text-[11px] text-[var(--text-primary)]" />
                      <label htmlFor="project-file-type" className="sr-only">Filter by file type</label>
                      <select id="project-file-type" value={fileType} onChange={(event) => { setFileType(event.target.value as typeof fileType); setFilePage(1); }} className="bg-[var(--bg-primary)] border border-[var(--border)] px-3 py-2 text-[11px] text-[var(--text-primary)]">
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
                      <div key={file.id} className="group flex items-center gap-3 border-b border-[var(--border)] last:border-b-0 bg-[var(--bg-primary)] px-4 py-3">
                        <span className="w-20 shrink-0 font-mono text-[8px] uppercase tracking-[.1em] text-[var(--text-muted)]">{typeLabel(file.file_type)}</span>
                        <span className="min-w-0 flex-1 truncate text-[11px] text-[var(--text-primary)]" title={file.name}>{file.name}</span>
                        <span className="hidden md:block font-mono text-[9px] uppercase text-[var(--text-muted)]">{file.status ?? 'ready'}</span>
                        {canEditFiles && (
                          <button type="button" disabled={deletingId === file.id} onClick={() => void removeFile(file)} aria-label={`Delete ${file.name}`} className="px-2 py-1 font-mono text-[9px] uppercase text-[var(--text-muted)] hover:text-[var(--danger)] disabled:opacity-40">{deletingId === file.id ? 'Deleting…' : 'Delete'}</button>
                        )}
                      </div>
                    ))}
                  </div>

                  {filteredFiles.length > PAGE_SIZE && (
                    <div className="flex items-center justify-between border-t border-[var(--border)] px-4 py-3">
                      <button type="button" disabled={filePage === 1} onClick={() => setFilePage((page) => Math.max(1, page - 1))} className="font-mono text-[9px] uppercase text-[var(--text-secondary)] disabled:opacity-30">← Previous</button>
                      <span className="font-mono text-[9px] text-[var(--text-muted)]">Page {filePage.toLocaleString()} / {pageCount.toLocaleString()}</span>
                      <button type="button" disabled={filePage === pageCount} onClick={() => setFilePage((page) => Math.min(pageCount, page + 1))} className="font-mono text-[9px] uppercase text-[var(--text-secondary)] disabled:opacity-30">Next →</button>
                    </div>
                  )}
                </section>

                <QueryHistory projectId={current.project_id} />

                {canRename && (
                  <section className="mt-6 border border-[var(--border)] bg-[var(--wash)] p-4 flex items-center justify-between gap-4">
                    <div><p className="font-mono text-[9px] uppercase text-[var(--text-muted)]">Project lifecycle</p><p className="mt-1 text-[10px] text-[var(--text-secondary)]">Archiving hides the project but retains its documents and evidence.</p></div>
                    <button type="button" onClick={() => void archiveCurrent()} className="shrink-0 border border-[var(--danger)] px-3 py-2 font-mono text-[9px] uppercase text-[var(--danger)]">Archive project</button>
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
