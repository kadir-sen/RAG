import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import FileUploadArea from '../components/files/FileUploadArea';
import { archiveProject, createProject, renameProject } from '../api/projectApi';
import { getIndexingStatus, uploadFile } from '../api/fileApi';
import type { IndexingStatus } from '../types/api';
import { useProjectStore } from '../stores/projectStore';
import QueryHistory from '../components/projects/QueryHistory';

function duration(seconds: number | null) {
  if (seconds == null) return 'calibrating';
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.ceil(seconds / 60);
  return minutes < 60 ? `${minutes}m` : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export default function ProjectsPage() {
  const navigate = useNavigate();
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
  const active = useMemo(() => jobs.filter((j) => !['ready', 'failed'].includes(j.status)), [jobs]);
  const readyCount = jobs.filter((job) => job.status === 'ready').length;
  const canOpen = (readyCount > 0 || Boolean(current?.stats.report_ready)) && active.length === 0;

  const addProject = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    try {
      const project = await createProject(name.trim());
      await load();
      select(project.project_id);
      setName('');
    } finally { setCreating(false); }
  };

  const addFiles = async (files: File[]) => {
    if (!selectedProjectId) return;
    setUploading(true);
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
    } finally { setUploading(false); }
  };

  const saveName = async () => {
    if (!current || !renameValue.trim()) return;
    await renameProject(current.project_id, renameValue.trim());
    setRenameValue('');
    await load();
  };

  const archiveCurrent = async () => {
    if (!current || !window.confirm(`Archive project “${current.name}”?`)) return;
    await archiveProject(current.project_id);
    select(null);
    await load();
  };

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-6xl mx-auto px-6 py-10">
        <header className="mb-8">
          <p className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-muted)]">Project management</p>
          <h1 className="mt-2 text-2xl font-semibold text-[var(--text-primary)]">Select the project record</h1>
          <p className="mt-2 text-[13px] text-[var(--text-secondary)]">Documents, chats, chronologies and reports remain isolated inside the selected project.</p>
        </header>

        <div className="grid lg:grid-cols-[1fr_340px] gap-6">
          <section>
            <div className="grid sm:grid-cols-2 gap-4">
              {projects.map((project) => (
                <button
                  type="button"
                  key={project.project_id}
                  onClick={() => select(project.project_id)}
                  className={`text-left border rounded-[3px] p-4 bg-[var(--wash)] transition-colors ${selectedProjectId === project.project_id ? 'border-[var(--accent)]' : 'border-[var(--border)] hover:border-[var(--ink)]'}`}
                >
                  <div className="flex justify-between gap-3">
                    <h2 className="text-[15px] font-semibold text-[var(--text-primary)]">{project.name}</h2>
                    <span className="font-mono text-[9px] uppercase text-[var(--text-muted)]">{project.role}</span>
                  </div>
                  <p className="mt-3 font-mono text-[10px] text-[var(--text-secondary)]">
                    {project.stats.files.document} docs · {project.stats.files.email} mail · {project.stats.files.data} sheets
                  </p>
                  <p className="mt-1 text-[11px] text-[var(--text-muted)]">
                    {project.stats.report_ready ? 'Report ready' : `${project.stats.queued + project.stats.processing} remaining · ETA ${duration(project.stats.eta_seconds)}`}
                  </p>
                </button>
              ))}
            </div>
            {!loading && projects.length === 0 && (
              <div className="border border-[var(--border)] rounded-[3px] p-8 text-[13px] text-[var(--text-secondary)]">Create the first project to begin.</div>
            )}

            {current && (
              <>
              <div className="mt-6 border border-[var(--border)] bg-[var(--wash)] rounded-[3px]">
                <div className="p-4 border-b border-[var(--border)] flex items-center justify-between gap-4">
                  <div>
                    <h2 className="text-[15px] font-semibold text-[var(--text-primary)]">{current.name} · {current.stats.report_ready ? 'ready' : 'processing'}</h2>
                    <p className="text-[11px] text-[var(--text-muted)] mt-1">{active.length} active · {Math.max(readyCount, current.stats.ready)} ready · {Math.max(jobs.filter((j) => j.status === 'failed').length, current.stats.failed)} failed</p>
                    {!current.stats.calibration_complete && current.stats.total_files > 20 && <p className="mt-1 text-[10px] text-[var(--text-muted)]">Calibrating first {current.stats.calibration_size} files before releasing the remaining queue.</p>}
                  </div>
                  <button type="button" disabled={!canOpen} onClick={() => navigate('/')} className="px-3 py-2 bg-[var(--accent)] text-[var(--accent-ink)] font-mono text-[10px] uppercase tracking-[.14em] rounded-[2px] disabled:opacity-40">{canOpen ? 'Open modules →' : 'Processing record…'}</button>
                </div>
                <div className="p-3">{current.role === 'viewer'
                  ? <p className="p-3 text-[11px] text-[var(--text-muted)]">Viewer access · uploads are read-only.</p>
                  : <FileUploadArea onUpload={addFiles} isUploading={uploading} />}</div>
                <div className="max-h-72 overflow-y-auto border-t border-[var(--border)]">
                  {jobs.map((job) => (
                    <div key={job.file_id} className="px-4 py-3 border-b border-[var(--border)] last:border-b-0">
                      <div className="flex justify-between gap-4 text-[11px]"><span className="truncate text-[var(--text-primary)]">{job.filename}</span><span className="font-mono uppercase text-[var(--text-muted)]">{job.status}</span></div>
                      <div className="mt-2 h-1 bg-[var(--wash-firm)]"><div className="h-full bg-[var(--accent)]" style={{ width: `${Math.round(job.progress * 100)}%` }} /></div>
                      {job.error && <p className="mt-1 text-[10px] text-[var(--danger)]">{job.error}</p>}
                    </div>
                  ))}
                </div>
              </div>
              <QueryHistory projectId={current.project_id} />
              </>
            )}
          </section>

          <aside className="border border-[var(--border)] bg-[var(--wash)] rounded-[3px] p-4 h-fit">
            <h2 className="font-mono text-[10px] uppercase tracking-[.16em] text-[var(--text-muted)]">New project</h2>
            <form onSubmit={addProject} className="mt-3">
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Project name" className="w-full px-3 py-2 bg-[var(--bg-primary)] border border-[var(--border)] text-sm text-[var(--text-primary)] rounded-[2px]" />
              <button disabled={creating || !name.trim()} className="mt-3 w-full px-3 py-2 border border-[var(--border)] text-[11px] text-[var(--text-primary)] disabled:opacity-40">{creating ? 'Creating…' : 'Create project'}</button>
            </form>
            {current && ['owner', 'admin'].includes(current.role) && <div className="mt-6 border-t border-[var(--border)] pt-4">
              <p className="font-mono text-[10px] uppercase text-[var(--text-muted)]">Selected project</p>
              <div className="mt-2 flex gap-1"><input value={renameValue} onChange={(event) => setRenameValue(event.target.value)} placeholder={current.name} className="min-w-0 flex-1 bg-[var(--bg-primary)] border border-[var(--border)] px-2 py-1 text-[11px]" /><button type="button" onClick={() => void saveName()} className="border border-[var(--border)] px-2 text-[10px]">Rename</button></div>
              <button type="button" onClick={() => void archiveCurrent()} className="mt-2 text-[10px] text-[var(--danger)]">Archive project</button>
            </div>}
            <p className="mt-5 text-[11px] leading-5 text-[var(--text-muted)]">The local BGE profile is fixed for this project. OCR uses two concurrent documents and two page workers initially; ETA calibrates from completed files.</p>
          </aside>
        </div>
      </div>
    </div>
  );
}
