import { useEffect, useMemo, useRef, useState } from 'react';
import AIReportPanel from '../components/reports/AIReportPanel';
import { deleteProgramme, launchToolkit, listProgrammes, uploadProgramme } from '../api/toolkitApi';
import type { ProgrammeFile } from '../api/toolkitApi';
import { useProjectStore } from '../stores/projectStore';
import { useAuthStore } from '../stores/authStore';

function errorMessage(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (detail === 'toolkit_analysis_size_exceeded') return 'The programme set exceeds the 75 MB analysis limit.';
  if (detail === 'programme_required') return 'Upload at least one Primavera P6 XER file first.';
  if (typeof detail === 'string') return detail;
  return 'The Delay Analysis Toolkit request could not be completed.';
}

export default function ForensicPage() {
  const selectedProjectId = useProjectStore((state) => state.selectedProjectId);
  const projects = useProjectStore((state) => state.projects);
  const reloadProjects = useProjectStore((state) => state.load);
  const refreshMe = useAuthStore((state) => state.refreshMe);
  const inputRef = useRef<HTMLInputElement>(null);
  const [programmes, setProgrammes] = useState<ProgrammeFile[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const project = projects.find((item) => item.project_id === selectedProjectId);
  const canEdit = Boolean(project && project.role !== 'viewer');
  const totalBytes = useMemo(
    () => programmes.reduce((total, item) => total + item.size_bytes, 0),
    [programmes],
  );

  useEffect(() => {
    setProgrammes([]);
    setError('');
    if (selectedProjectId) void listProgrammes().then(setProgrammes).catch((cause) => setError(errorMessage(cause)));
  }, [selectedProjectId]);

  const upload = async (file: File) => {
    setBusy(true); setError('');
    try {
      await uploadProgramme(file);
      setProgrammes(await listProgrammes());
      await Promise.all([reloadProjects(), refreshMe()]);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  const remove = async (file: ProgrammeFile) => {
    if (!window.confirm(`Delete “${file.name}” from this project?`)) return;
    setBusy(true); setError('');
    try {
      await deleteProgramme(file.file_id);
      setProgrammes(await listProgrammes());
      await Promise.all([reloadProjects(), refreshMe()]);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally { setBusy(false); }
  };

  const openToolkit = async () => {
    setBusy(true); setError('');
    try {
      const launch = await launchToolkit();
      window.location.assign(launch.launch_url);
    } catch (cause) {
      setError(errorMessage(cause));
      setBusy(false);
    }
  };

  return (
    <div className="flex-1 min-w-0 overflow-y-auto">
      <AIReportPanel module="forensic" />
      <div className="max-w-4xl mx-auto px-4 md:px-8 py-8">
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">Forensic Reports</h1>
        <p className="mt-2 text-[13px] leading-6 text-[var(--text-secondary)]">Generate a project-grounded draft above. Findings carry supporting evidence, counter-evidence, confidence and missing-record fields. “Issue” uses the strict verification gate.</p>
        <div className="mt-6 border border-[var(--border)] bg-[var(--wash)] rounded-[3px] p-5">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="font-mono text-[10px] uppercase tracking-[.16em] text-[var(--text-muted)]">Delay Analysis Toolkit</p>
              <p className="mt-2 text-[12px] text-[var(--text-secondary)]">Run programme calculations, DCMA checks and critical-path analysis against the active project's P6 files. AI narratives use managed Gemini 3.6 Flash and the project's credit balance.</p>
              <p className="mt-2 font-mono text-[9px] text-[var(--text-muted)]">{programmes.length} files · {(totalBytes / 1048576).toFixed(2)} / 75.00 MB analysis capacity</p>
            </div>
            <button type="button" disabled={busy || programmes.length === 0 || !canEdit} onClick={() => void openToolkit()} className="shrink-0 bg-[var(--accent)] px-4 py-2 font-mono text-[10px] uppercase tracking-[.12em] text-[var(--accent-ink)] disabled:opacity-40">{busy ? 'Working…' : 'Open toolkit →'}</button>
          </div>
          {error && <p role="alert" className="mt-3 text-[11px] text-[var(--danger)]">{error}</p>}
          <div className="mt-4 border-t border-[var(--border)]">
            {programmes.map((file) => (
              <div key={file.file_id} className="flex items-center gap-3 border-b border-[var(--border)] py-3 text-[11px]">
                <span className="font-mono text-[8px] uppercase text-[var(--text-muted)]">XER</span>
                <span className="min-w-0 flex-1 truncate text-[var(--text-primary)]">{file.name}</span>
                <span className="font-mono text-[9px] text-[var(--text-muted)]">{(file.size_bytes / 1048576).toFixed(2)} MB</span>
                {canEdit && <button type="button" disabled={busy} onClick={() => void remove(file)} className="font-mono text-[9px] uppercase text-[var(--text-muted)] hover:text-[var(--danger)] disabled:opacity-40">Delete</button>}
              </div>
            ))}
            {programmes.length === 0 && <p className="py-4 text-[11px] text-[var(--text-muted)]">No programme files in this project yet.</p>}
          </div>
          {canEdit ? (
            <label className="mt-4 inline-flex cursor-pointer items-center border border-[var(--border)] px-3 py-2 font-mono text-[9px] uppercase text-[var(--text-secondary)] hover:border-[var(--ink)]">
              {busy ? 'Uploading…' : '+ Add P6 XER'}
              <input ref={inputRef} type="file" accept=".xer" disabled={busy} className="sr-only" onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); }} />
            </label>
          ) : <p className="mt-4 text-[10px] text-[var(--text-muted)]">Viewer access · programme upload and toolkit launch are disabled.</p>}
        </div>
      </div>
    </div>
  );
}
