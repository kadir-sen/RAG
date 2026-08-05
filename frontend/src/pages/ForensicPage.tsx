import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import AIReportPanel from '../components/reports/AIReportPanel';
import {
  createForensicRun,
  createWorkspace,
  deleteProgramme,
  downloadForensicArtifact,
  fetchForensicArtifact,
  getForensicRun,
  getForensicStatus,
  listForensicRuns,
  listProgrammes,
  listWorkspaces,
  retryForensicRun,
  updateWorkspace,
  uploadProgramme,
} from '../api/forensicApi';
import type { ForensicRun, ProgrammeFile, ResultTable } from '../api/forensicApi';
import { useProjectStore } from '../stores/projectStore';
import { useAuthStore } from '../stores/authStore';

const NAVIGATION = [
  {
    label: 'Forensic Programme Analysis',
    items: [
      ['intake', 'Intake'], ['dcma', 'DCMA'],
      ['baseline-critical-path', 'Baseline Critical Path'],
      ['revision-comparison', 'Revision Comparison'],
      ['out-of-sequence', 'Out-of-Sequence'], ['float-erosion', 'Float Erosion'],
      ['progress-s-curve', 'Progress S-Curve'], ['resource-loading', 'Resource Loading'],
      ['sequence-coding', 'Sequence Coding'], ['hierarchy', 'Hierarchy'],
      ['milestone-shift', 'Milestone Shift'], ['progress-transfer', 'Progress Transfer'],
      ['as-built-critical-path', 'As-Built Critical Path'],
      ['report-assembler', 'Report Assembler'],
    ],
  },
  {
    label: 'Retrospective',
    items: [
      ['as-planned-vs-as-built', 'As-Planned vs As-Built'],
      ['windows-analysis', 'Windows Analysis'],
      ['impacted-as-planned', 'Impacted As-Planned'],
      ['collapsed-as-built', 'Collapsed As-Built'],
    ],
  },
  { label: 'Prospective', items: [['time-impact-analysis', 'Time Impact Analysis']] },
] as const;

const MODULE_OPTIONS: Array<{ slug: string; label: string }> = NAVIGATION.flatMap(
  (group) => group.items.map(([slug, label]) => ({ slug, label })),
);

const PROGRAMME_INDEX_MODULES = new Set([
  'dcma', 'baseline-critical-path', 'out-of-sequence', 'resource-loading',
  'sequence-coding', 'hierarchy', 'collapsed-as-built', 'time-impact-analysis',
]);

function bytes(value: number) {
  if (value < 1_000_000) return `${(value / 1000).toFixed(1)} KB`;
  return `${(value / 1_000_000).toFixed(1)} MB`;
}

function readable(value: unknown): string {
  if (value == null) return '—';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function errorMessage(error: unknown) {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === 'string') return detail.replaceAll('_', ' ');
  return error instanceof Error ? error.message : 'The operation could not be completed.';
}

function ResultTableView({ table }: { table: ResultTable }) {
  const columns = useMemo(
    () => Array.from(new Set(table.rows.flatMap((row) => Object.keys(row)))),
    [table.rows],
  );
  if (!table.rows.length) return null;
  return (
    <section className="border border-[var(--border)] bg-[var(--bg-primary)]">
      <div className="flex items-center justify-between gap-4 border-b border-[var(--border)] px-4 py-3">
        <h3 className="font-mono text-[10px] uppercase tracking-[.13em] text-[var(--text-muted)]">{table.name.replace('result.', '')}</h3>
        <span className="font-mono text-[9px] text-[var(--text-muted)]">{table.total_rows.toLocaleString()} rows{table.truncated ? ' · preview' : ''}</span>
      </div>
      <div className="max-h-[460px] overflow-auto">
        <table className="w-full min-w-[760px] border-collapse text-left text-[11px]">
          <thead className="sticky top-0 bg-[var(--wash)]">
            <tr>{columns.map((column) => <th key={column} className="border-b border-r border-[var(--border)] px-3 py-2 font-mono text-[9px] uppercase text-[var(--text-muted)]">{column.replaceAll('_', ' ')}</th>)}</tr>
          </thead>
          <tbody>{table.rows.map((row, index) => (
            <tr key={index} className="odd:bg-[var(--wash)]/40">
              {columns.map((column) => <td key={column} className="max-w-[360px] border-b border-r border-[var(--border)] px-3 py-2 align-top text-[var(--text-secondary)]"><span className="line-clamp-5">{readable(row[column])}</span></td>)}
            </tr>
          ))}</tbody>
        </table>
      </div>
    </section>
  );
}

function VegaLitePanel({ spec }: { spec: Record<string, unknown> }) {
  const target = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let finalizer: (() => void) | undefined;
    let live = true;
    void import('vega-embed').then(async ({ default: embed }) => {
      if (!live || !target.current) return;
      const result = await embed(
        target.current,
        spec as Parameters<typeof embed>[1],
        { actions: false, renderer: 'canvas' },
      );
      finalizer = () => result.finalize();
    });
    return () => { live = false; finalizer?.(); };
  }, [spec]);
  return <div className="overflow-hidden border border-[var(--border)] bg-[var(--bg-primary)] p-4"><div ref={target} className="w-full" aria-label="Analysis chart" /></div>;
}

function SandboxedHtmlPanel({ artifactId, title }: { artifactId: string; title: string }) {
  const [url, setUrl] = useState('');
  useEffect(() => {
    let live = true;
    let objectUrl = '';
    void fetchForensicArtifact(artifactId).then((blob) => {
      if (!live) return;
      objectUrl = URL.createObjectURL(blob);
      setUrl(objectUrl);
    });
    return () => { live = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [artifactId]);
  if (!url) return <div className="h-40 border border-[var(--border)] p-4 text-[10px] text-[var(--text-muted)]">Loading visual…</div>;
  return <iframe title={title} src={url} sandbox="allow-scripts" className="h-[620px] w-full border border-[var(--border)] bg-white" />;
}

type ModuleFormState = {
  programmeIndex: number;
  method: string;
  threshold: string;
  endTask: string;
  weight: string;
  dimensions: string;
  removeCodes: string;
  reportTitle: string;
  dateBasis: string;
  eventId: string;
  eventTitle: string;
  eventDate: string;
  eventDescription: string;
  eventDuration: string;
  predecessor: string;
  successor: string;
};

const INITIAL_FORM: ModuleFormState = {
  programmeIndex: -1, method: 'longest_path', threshold: '10', endTask: '',
  weight: 'duration', dimensions: '', removeCodes: '',
  reportTitle: 'Forensic Programme Analysis', dateBasis: 'target',
  eventId: 'EV-001', eventTitle: '', eventDate: '', eventDescription: '',
  eventDuration: '10', predecessor: '', successor: '',
};

function eventPayload(form: ModuleFormState) {
  return [{
    event: {
      event_id: form.eventId, title: form.eventTitle,
      description: form.eventDescription, date_raised: form.eventDate,
      responsibility_asserted: '', evidence_note: '', area: '', discipline: '',
      project_context: '', work_package: '',
    },
    fragnet: [{
      id: `${form.eventId}-FRAG-01`, name: form.eventTitle,
      duration_days: Number(form.eventDuration),
      predecessors: form.predecessor ? [{ id: form.predecessor, type: 'FS', lag_days: 0 }] : [],
      successors: form.successor ? [{ id: form.successor, type: 'FS', lag_days: 0 }] : [],
      rationale: 'Analyst-defined event fragnet', assumptions: '', confidence: 'medium', calendar_id: '',
    }],
  }];
}

function parametersFor(slug: string, form: ModuleFormState): Record<string, unknown> {
  switch (slug) {
    case 'dcma': return { programme_index: form.programmeIndex, thresholds: {} };
    case 'baseline-critical-path': return { programme_index: form.programmeIndex, method: form.method, near_critical_days: Number(form.threshold), float_tolerance_days: 0, branch_tolerance_hours: 1, end_task_code: form.endTask };
    case 'revision-comparison': return { old_index: 0, new_index: -1, end_task_code: form.endTask };
    case 'out-of-sequence': return { programme_index: form.programmeIndex };
    case 'float-erosion': return { near_critical_days: Number(form.threshold) };
    case 'progress-s-curve': return { weight_scheme: form.weight };
    case 'resource-loading': return { programme_index: form.programmeIndex };
    case 'sequence-coding': return { programme_index: form.programmeIndex, mapping_confirmed: false, min_front_activities: 3 };
    case 'hierarchy': return { programme_index: form.programmeIndex, dimension_ids: form.dimensions.split(',').map((v) => v.trim()).filter(Boolean) };
    case 'milestone-shift': return {};
    case 'progress-transfer': return { network_index: 0, progress_index: -1 };
    case 'as-built-critical-path': return { end_task_code: form.endTask, max_gap_days: 15, allow_temporal_fallback: true, allow_forecast_tail: true };
    case 'report-assembler': return { report_title: form.reportTitle };
    case 'as-planned-vs-as-built': return { activity_codes: [], date_basis: form.dateBasis };
    case 'windows-analysis': return { end_task_code: form.endTask, switch_threshold: .5, bifurcate: true };
    case 'impacted-as-planned': return { events: eventPayload(form) };
    case 'collapsed-as-built': return { programme_index: form.programmeIndex, remove_activity_codes: form.removeCodes.split(/[\s,]+/).filter(Boolean), anchor_code: '' };
    case 'time-impact-analysis': return { programme_index: form.programmeIndex, events: eventPayload(form), target_milestone: form.endTask };
    default: return {};
  }
}

function ModuleForm({ slug, programmes, form, setForm }: {
  slug: string;
  programmes: ProgrammeFile[];
  form: ModuleFormState;
  setForm: React.Dispatch<React.SetStateAction<ModuleFormState>>;
}) {
  const input = 'w-full border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2 text-[12px] text-[var(--text-primary)]';
  const set = (key: keyof ModuleFormState, value: string | number) => setForm((old) => ({ ...old, [key]: value }));
  const needsEvent = slug === 'time-impact-analysis' || slug === 'impacted-as-planned';
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {PROGRAMME_INDEX_MODULES.has(slug) && (
        <label className="text-[10px] uppercase tracking-[.12em] text-[var(--text-muted)]">Programme
          <select value={form.programmeIndex} onChange={(e) => set('programmeIndex', Number(e.target.value))} className={`${input} mt-1 normal-case tracking-normal`}>
            {programmes.map((programme, index) => <option key={programme.file_id} value={index}>{programme.name}</option>)}
          </select>
        </label>
      )}
      {slug === 'baseline-critical-path' && <label className="text-[10px] uppercase tracking-[.12em] text-[var(--text-muted)]">Identification method<select value={form.method} onChange={(e) => set('method', e.target.value)} className={`${input} mt-1 normal-case`}><option value="longest_path">Longest path</option><option value="float">Total float</option></select></label>}
      {['baseline-critical-path', 'float-erosion'].includes(slug) && <label className="text-[10px] uppercase tracking-[.12em] text-[var(--text-muted)]">Near-critical threshold (days)<input type="number" min="0" value={form.threshold} onChange={(e) => set('threshold', e.target.value)} className={`${input} mt-1 normal-case`} /></label>}
      {['baseline-critical-path', 'revision-comparison', 'as-built-critical-path', 'windows-analysis', 'time-impact-analysis'].includes(slug) && <label className="text-[10px] uppercase tracking-[.12em] text-[var(--text-muted)]">Completion milestone (optional)<input value={form.endTask} onChange={(e) => set('endTask', e.target.value)} placeholder="Activity ID" className={`${input} mt-1 normal-case`} /></label>}
      {slug === 'progress-s-curve' && <label className="text-[10px] uppercase tracking-[.12em] text-[var(--text-muted)]">Weighting<select value={form.weight} onChange={(e) => set('weight', e.target.value)} className={`${input} mt-1 normal-case`}><option value="duration">Activity duration</option><option value="count">Activity count</option><option value="resource_qty">Resource quantity</option></select></label>}
      {slug === 'hierarchy' && <label className="sm:col-span-2 text-[10px] uppercase tracking-[.12em] text-[var(--text-muted)]">Dimension IDs (optional, comma separated)<input value={form.dimensions} onChange={(e) => set('dimensions', e.target.value)} placeholder="Leave empty to use the first available dimensions" className={`${input} mt-1 normal-case`} /></label>}
      {slug === 'collapsed-as-built' && <label className="sm:col-span-2 text-[10px] uppercase tracking-[.12em] text-[var(--text-muted)]">Confirmed event activity IDs<textarea required value={form.removeCodes} onChange={(e) => set('removeCodes', e.target.value)} placeholder="A1000, A1010" className={`${input} mt-1 min-h-24 normal-case`} /></label>}
      {slug === 'report-assembler' && <label className="sm:col-span-2 text-[10px] uppercase tracking-[.12em] text-[var(--text-muted)]">Report title<input value={form.reportTitle} onChange={(e) => set('reportTitle', e.target.value)} className={`${input} mt-1 normal-case`} /></label>}
      {slug === 'as-planned-vs-as-built' && <label className="text-[10px] uppercase tracking-[.12em] text-[var(--text-muted)]">Baseline date basis<select value={form.dateBasis} onChange={(e) => set('dateBasis', e.target.value)} className={`${input} mt-1 normal-case`}><option value="target">Target dates</option><option value="late">Late dates</option><option value="early">Early dates</option></select></label>}
      {needsEvent && <>
        <div className="sm:col-span-2 border-t border-[var(--border)] pt-4"><p className="font-mono text-[9px] uppercase tracking-[.14em] text-[var(--text-muted)]">Analyst-confirmed delay event and fragnet</p></div>
        <label className="text-[10px] uppercase text-[var(--text-muted)]">Event ID<input required value={form.eventId} onChange={(e) => set('eventId', e.target.value)} className={`${input} mt-1 normal-case`} /></label>
        <label className="text-[10px] uppercase text-[var(--text-muted)]">Event date<input type="date" value={form.eventDate} onChange={(e) => set('eventDate', e.target.value)} className={`${input} mt-1 normal-case`} /></label>
        <label className="sm:col-span-2 text-[10px] uppercase text-[var(--text-muted)]">Event title<input required value={form.eventTitle} onChange={(e) => set('eventTitle', e.target.value)} className={`${input} mt-1 normal-case`} /></label>
        <label className="sm:col-span-2 text-[10px] uppercase text-[var(--text-muted)]">Description<textarea value={form.eventDescription} onChange={(e) => set('eventDescription', e.target.value)} className={`${input} mt-1 min-h-20 normal-case`} /></label>
        <label className="text-[10px] uppercase text-[var(--text-muted)]">Duration (working days)<input type="number" min="0" required value={form.eventDuration} onChange={(e) => set('eventDuration', e.target.value)} className={`${input} mt-1 normal-case`} /></label>
        <label className="text-[10px] uppercase text-[var(--text-muted)]">Tie-in predecessor<input required value={form.predecessor} onChange={(e) => set('predecessor', e.target.value)} placeholder="Activity ID" className={`${input} mt-1 normal-case`} /></label>
        <label className="text-[10px] uppercase text-[var(--text-muted)]">Tie-in successor<input required value={form.successor} onChange={(e) => set('successor', e.target.value)} placeholder="Activity ID" className={`${input} mt-1 normal-case`} /></label>
      </>}
    </div>
  );
}

function IntakePanel({ canEdit, workspaceId, onWorkspace }: { canEdit: boolean; workspaceId: string; onWorkspace: (id: string) => void }) {
  const queryClient = useQueryClient();
  const programmes = useQuery({ queryKey: ['forensic-programmes'], queryFn: listProgrammes });
  const workspaces = useQuery({ queryKey: ['forensic-workspaces'], queryFn: listWorkspaces });
  const [selected, setSelected] = useState<string[]>([]);
  const [name, setName] = useState('Programme Analysis');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const workspace = workspaces.data?.find((item) => item.workspace_id === workspaceId);
    if (workspace) { setSelected(workspace.programme_ids); setName(workspace.name); }
  }, [workspaceId, workspaces.data]);

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true); setError('');
    try {
      for (const file of Array.from(files)) await uploadProgramme(file);
      await Promise.all([queryClient.invalidateQueries({ queryKey: ['forensic-programmes'] }), useAuthStore.getState().refreshMe()]);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  };
  const save = async () => {
    if (!selected.length) return;
    setBusy(true); setError('');
    try {
      const existing = workspaces.data?.find((item) => item.workspace_id === workspaceId);
      const workspace = existing
        ? await updateWorkspace(existing.workspace_id, { name, programme_ids: selected })
        : await createWorkspace({ name, programme_ids: selected, settings: {} });
      await queryClient.invalidateQueries({ queryKey: ['forensic-workspaces'] });
      onWorkspace(workspace.workspace_id);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  };
  return (
    <div className="space-y-6">
      <section className="border border-[var(--border)] bg-[var(--wash)] p-5">
        <p className="font-mono text-[9px] uppercase tracking-[.15em] text-[var(--text-muted)]">Project XER library</p>
        <h2 className="mt-2 text-lg font-semibold text-[var(--text-primary)]">Persistent programme sources</h2>
        <p className="mt-2 max-w-2xl text-[12px] leading-5 text-[var(--text-secondary)]">Primavera XER files remain inside this COAir project, count toward source storage, and never enter OCR, embeddings or document retrieval.</p>
        {canEdit && <label className="mt-4 inline-flex cursor-pointer border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-[11px] font-medium text-[var(--accent-ink)]">{busy ? 'Working…' : 'Upload XER files'}<input type="file" accept=".xer" multiple disabled={busy} onChange={(e) => void upload(e.target.files)} className="sr-only" /></label>}
      </section>
      {error && <p role="alert" className="border border-[var(--danger)] p-3 text-[11px] text-[var(--danger)]">{error}</p>}
      <section className="border border-[var(--border)] bg-[var(--bg-primary)]">
        <div className="border-b border-[var(--border)] p-4"><h2 className="text-[14px] font-semibold text-[var(--text-primary)]">Select the programme set</h2><p className="mt-1 text-[10px] text-[var(--text-muted)]">Combined selected size may not exceed 75 MiB.</p></div>
        <div className="divide-y divide-[var(--border)]">
          {(programmes.data ?? []).map((programme) => <div key={programme.file_id} className="flex items-center gap-3 p-4">
            <input type="checkbox" checked={selected.includes(programme.file_id)} disabled={!canEdit} onChange={(e) => setSelected((old) => e.target.checked ? [...old, programme.file_id] : old.filter((id) => id !== programme.file_id))} />
            <div className="min-w-0 flex-1"><p className="truncate text-[12px] font-medium text-[var(--text-primary)]">{programme.name}</p><p className="mt-1 font-mono text-[9px] text-[var(--text-muted)]">{bytes(programme.size_bytes)} · SHA {programme.sha256.slice(0, 12)}</p></div>
            {canEdit && <button type="button" className="font-mono text-[9px] uppercase text-[var(--danger)]" onClick={async () => { if (!window.confirm(`Delete ${programme.name}?`)) return; await deleteProgramme(programme.file_id); setSelected((old) => old.filter((id) => id !== programme.file_id)); await queryClient.invalidateQueries({ queryKey: ['forensic-programmes'] }); }}>Delete</button>}
          </div>)}
          {!programmes.isLoading && !programmes.data?.length && <p className="p-6 text-[11px] text-[var(--text-muted)]">No XER programmes are stored in this project.</p>}
        </div>
        {canEdit && <div className="flex flex-col gap-3 border-t border-[var(--border)] bg-[var(--wash)] p-4 sm:flex-row"><input value={name} onChange={(e) => setName(e.target.value)} className="min-w-0 flex-1 border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2 text-[12px]" /><button disabled={busy || !selected.length || !name.trim()} onClick={() => void save()} className="border border-[var(--ink)] px-4 py-2 text-[11px] text-[var(--text-primary)] disabled:opacity-40">{workspaceId ? 'Update workspace' : 'Create workspace'}</button></div>}
      </section>
    </div>
  );
}

function RunPanel({ slug, workspaceId, programmes, canEdit }: { slug: string; workspaceId: string; programmes: ProgrammeFile[]; canEdit: boolean }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState(INITIAL_FORM);
  const [selectedRunId, setSelectedRunId] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [aiNarrative, setAiNarrative] = useState(false);
  const [error, setError] = useState('');
  const runs = useQuery({ queryKey: ['forensic-runs', workspaceId], queryFn: () => listForensicRuns(workspaceId), enabled: Boolean(workspaceId), refetchInterval: 2500 });
  const relevant = useMemo(() => (runs.data ?? []).filter((run) => run.module_slug === slug), [runs.data, slug]);
  useEffect(() => { setSelectedRunId(relevant[0]?.run_id ?? ''); }, [slug, relevant[0]?.run_id]);
  const selected = useQuery({ queryKey: ['forensic-run', selectedRunId], queryFn: () => getForensicRun(selectedRunId), enabled: Boolean(selectedRunId), refetchInterval: (query) => ['queued', 'processing'].includes((query.state.data as ForensicRun | undefined)?.status ?? '') ? 1500 : false });
  const run = selected.data ?? relevant.find((item) => item.run_id === selectedRunId) ?? null;
  const submit = async () => {
    setSubmitting(true); setError('');
    try {
      const created = await createForensicRun(workspaceId, slug, parametersFor(slug, form), aiNarrative);
      setSelectedRunId(created.run_id);
      await queryClient.invalidateQueries({ queryKey: ['forensic-runs', workspaceId] });
    } catch (e) { setError(errorMessage(e)); } finally { setSubmitting(false); }
  };
  return (
    <div className="space-y-6">
      <section className="border border-[var(--border)] bg-[var(--wash)] p-5">
        <ModuleForm slug={slug} programmes={programmes} form={form} setForm={setForm} />
        {error && <p role="alert" className="mt-4 text-[11px] text-[var(--danger)]">{error}</p>}
        {slug !== 'intake' && <label className="mt-5 flex items-start gap-2 text-[10px] leading-4 text-[var(--text-secondary)]"><input type="checkbox" checked={aiNarrative} onChange={(e) => setAiNarrative(e.target.checked)} /><span>Add a Gemini 3.6 Flash expert narrative. Deterministic calculations remain free; only this optional narrative uses project credits.</span></label>}
        <button disabled={!canEdit || submitting || !workspaceId} onClick={() => void submit()} className="mt-4 border border-[var(--accent)] bg-[var(--accent)] px-5 py-2.5 text-[11px] font-medium text-[var(--accent-ink)] disabled:opacity-40">{submitting ? 'Queuing…' : 'Run analysis'}</button>
        {!canEdit && <p className="mt-2 text-[10px] text-[var(--text-muted)]">Viewer access is read-only.</p>}
      </section>
      {relevant.length > 0 && <section className="border border-[var(--border)] bg-[var(--bg-primary)] p-4"><p className="font-mono text-[9px] uppercase tracking-[.14em] text-[var(--text-muted)]">Run history</p><div className="mt-3 flex flex-wrap gap-2">{relevant.map((item) => <button key={item.run_id} onClick={() => setSelectedRunId(item.run_id)} className={`border px-3 py-2 text-[10px] ${selectedRunId === item.run_id ? 'border-[var(--accent)]' : 'border-[var(--border)]'}`}>{new Date(item.created_at).toLocaleString()} · {item.status}</button>)}</div></section>}
      {run && <section className="space-y-5">
        <div className="border border-[var(--border)] bg-[var(--wash)] p-4">
          <div className="flex items-center justify-between gap-4"><div><p className="font-mono text-[9px] uppercase text-[var(--text-muted)]">{run.stage.replaceAll('_', ' ')}</p><p className="mt-1 text-[12px] font-medium text-[var(--text-primary)]">{run.status === 'ready' ? 'Analysis complete' : run.status === 'failed' ? 'Analysis stopped' : 'Engine is running'}</p></div><span className="font-mono text-[11px] text-[var(--text-secondary)]">{Math.round(run.progress * 100)}%</span></div>
          <div className="mt-3 h-1 bg-[var(--wash-firm)]"><div className="h-full bg-[var(--accent)] transition-all" style={{ width: `${run.progress * 100}%` }} /></div>
          {run.error_code && <div className="mt-3 flex items-center justify-between"><p className="text-[11px] text-[var(--danger)]">{run.error_code.replaceAll('_', ' ')}</p>{canEdit && <button onClick={async () => { await retryForensicRun(run.run_id); await selected.refetch(); }} className="border border-[var(--border)] px-3 py-1.5 text-[10px]">Retry</button>}</div>}
        </div>
        {run.result && <>
          {run.result.metrics.length > 0 && <div className="grid grid-cols-2 gap-px border border-[var(--border)] bg-[var(--border)] md:grid-cols-4">{run.result.metrics.map((metric) => <div key={metric.label} className="bg-[var(--bg-primary)] p-4"><p className="font-mono text-[8px] uppercase text-[var(--text-muted)]">{metric.label}</p><p className="mt-2 break-words text-lg font-semibold text-[var(--text-primary)]">{readable(metric.value)}</p></div>)}</div>}
          {run.result.warnings.length > 0 && <div className="border border-[var(--amber)] p-4"><p className="font-mono text-[9px] uppercase text-[var(--amber)]">Engine warnings</p><ul className="mt-2 space-y-1 text-[11px] text-[var(--text-secondary)]">{run.result.warnings.map((warning, index) => <li key={index}>• {warning}</li>)}</ul></div>}
          {run.result.ai_status === 'credit_balance_exhausted' && <p className="border border-[var(--danger)] p-3 text-[11px] text-[var(--danger)]">Credit balance exhausted. The deterministic analysis and downloads remain available; add credits and start a new narrative run.</p>}
          {run.result.narrative && <section className="border border-[var(--border)] bg-[var(--bg-primary)] p-5"><p className="font-mono text-[9px] uppercase tracking-[.14em] text-[var(--text-muted)]">AI narrative · Gemini 3.6 Flash</p><p className="mt-3 whitespace-pre-wrap text-[12px] leading-6 text-[var(--text-secondary)]">{run.result.narrative}</p></section>}
          {run.result.chart && <VegaLitePanel spec={run.result.chart} />}
          {run.artifacts.filter((artifact) => artifact.kind === 'html').map((artifact) => <SandboxedHtmlPanel key={artifact.artifact_id} artifactId={artifact.artifact_id} title={artifact.name} />)}
          {run.result.tables.map((table) => <ResultTableView key={table.name} table={table} />)}
          <div className="flex flex-wrap gap-2">{run.artifacts.map((artifact) => <button key={artifact.artifact_id} onClick={() => void downloadForensicArtifact(artifact)} className="border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2 text-[10px] text-[var(--text-primary)]">Download {artifact.kind.toUpperCase()} · {bytes(artifact.size_bytes)}</button>)}</div>
          <details className="border border-[var(--border)] p-4"><summary className="cursor-pointer font-mono text-[9px] uppercase text-[var(--text-muted)]">Method caveats ({run.result.caveats.length})</summary><ul className="mt-3 space-y-2 text-[11px] leading-5 text-[var(--text-secondary)]">{run.result.caveats.map((value, index) => <li key={index}>• {value}</li>)}</ul></details>
        </>}
      </section>}
    </div>
  );
}

export default function ForensicPage() {
  const { moduleSlug = 'intake' } = useParams();
  const slug = moduleSlug;
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const workspaceId = searchParams.get('workspace') ?? '';
  const projects = useProjectStore((state) => state.projects);
  const selectedProjectId = useProjectStore((state) => state.selectedProjectId);
  const currentProject = projects.find((project) => project.project_id === selectedProjectId);
  const canEdit = currentProject?.role !== 'viewer';
  const status = useQuery({ queryKey: ['forensic-status'], queryFn: getForensicStatus });
  const programmes = useQuery({ queryKey: ['forensic-programmes'], queryFn: listProgrammes, enabled: status.data?.available });
  const workspaces = useQuery({ queryKey: ['forensic-workspaces'], queryFn: listWorkspaces, enabled: status.data?.available });
  const definition = status.data?.modules.find((item) => item.slug === slug);
  useEffect(() => {
    if (!workspaceId && workspaces.data?.length) setSearchParams({ workspace: workspaces.data[0].workspace_id }, { replace: true });
  }, [workspaceId, workspaces.data, setSearchParams]);
  useEffect(() => {
    if (status.data && !status.data.modules.some((item) => item.slug === slug) && slug !== 'evidence-report') navigate('/forensic/intake', { replace: true });
  }, [status.data, slug, navigate]);
  const selectedWorkspace = workspaces.data?.find((item) => item.workspace_id === workspaceId);
  const selectedProgrammes = (programmes.data ?? []).filter((item) => selectedWorkspace?.programme_ids.includes(item.file_id));

  if (status.isLoading) return <div className="flex-1 p-8 text-[12px] text-[var(--text-muted)]">Loading forensic engines…</div>;
  if (!status.data?.available) return <div className="flex-1 p-8"><div className="border border-[var(--border)] bg-[var(--wash)] p-6"><h1 className="text-lg font-semibold">Native forensic analysis is in validation</h1><p className="mt-2 text-[12px] text-[var(--text-secondary)]">An administrator can validate the pinned engines before enabling <code>FORENSIC_NATIVE_UI_V1</code> for project users.</p></div></div>;

  return (
    <div className="flex min-w-0 flex-1 overflow-hidden">
      <aside className="hidden w-[252px] shrink-0 overflow-y-auto border-r border-[var(--border)] bg-[var(--wash)] lg:block">
        <div className="border-b border-[var(--border)] p-4"><p className="font-mono text-[9px] uppercase tracking-[.15em] text-[var(--text-muted)]">Native COAir</p><h1 className="mt-1 text-[15px] font-semibold text-[var(--text-primary)]">Forensic Reports</h1><p className="mt-2 font-mono text-[8px] text-[var(--text-muted)]">COAIR {status.data.coair_sha.slice(0, 7)} · ENGINE {status.data.upstream_sha.slice(0, 7)}</p></div>
        <nav aria-label="Forensic analysis modules" className="p-3">{NAVIGATION.map((group) => <div key={group.label} className="mb-5"><p className="px-2 font-mono text-[8px] uppercase tracking-[.14em] text-[var(--text-muted)]">{group.label}</p><div className="mt-2 space-y-0.5">{group.items.map(([itemSlug, label]) => <Link key={itemSlug} to={`/forensic/${itemSlug}${workspaceId ? `?workspace=${workspaceId}` : ''}`} className={`block border-l-2 px-3 py-2 text-[10px] no-underline ${slug === itemSlug ? 'border-[var(--accent)] bg-[var(--bg-primary)] text-[var(--text-primary)]' : 'border-transparent text-[var(--text-secondary)] hover:border-[var(--border)]'}`}>{label}</Link>)}</div></div>)}<div className="border-t border-[var(--border)] pt-3"><Link to={`/forensic/evidence-report${workspaceId ? `?workspace=${workspaceId}` : ''}`} className={`block border-l-2 px-3 py-2 text-[10px] no-underline ${slug === 'evidence-report' ? 'border-[var(--accent)] bg-[var(--bg-primary)] text-[var(--text-primary)]' : 'border-transparent text-[var(--text-secondary)]'}`}>Evidence-led Forensic Draft</Link></div></nav>
      </aside>
      <div className="min-w-0 flex-1 overflow-y-auto">
        {slug === 'evidence-report' && <label className="m-4 block font-mono text-[9px] uppercase tracking-[.12em] text-[var(--text-muted)] lg:hidden">Analysis module<select value={slug} onChange={(e) => navigate(`/forensic/${e.target.value}${workspaceId ? `?workspace=${workspaceId}` : ''}`)} className="mt-1 block w-full border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2 text-[11px] normal-case text-[var(--text-primary)]">{MODULE_OPTIONS.map((item) => <option key={item.slug} value={item.slug}>{item.label}</option>)}<option value="evidence-report">Evidence-led Forensic Draft</option></select></label>}
        {slug === 'evidence-report' ? <AIReportPanel module="forensic" /> : <div className="mx-auto max-w-6xl px-4 py-6 md:px-8 md:py-8">
          <label className="mb-5 block font-mono text-[9px] uppercase tracking-[.12em] text-[var(--text-muted)] lg:hidden">Analysis module<select value={slug} onChange={(e) => navigate(`/forensic/${e.target.value}${workspaceId ? `?workspace=${workspaceId}` : ''}`)} className="mt-1 block w-full border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2 text-[11px] normal-case text-[var(--text-primary)]">{MODULE_OPTIONS.map((item) => <option key={item.slug} value={item.slug}>{item.label}</option>)}<option value="evidence-report">Evidence-led Forensic Draft</option></select></label>
          <header className="mb-6 flex flex-col gap-4 border-b border-[var(--border)] pb-5 md:flex-row md:items-end md:justify-between"><div><p className="font-mono text-[9px] uppercase tracking-[.15em] text-[var(--text-muted)]">{definition?.group ?? 'Programme'} · deterministic engine</p><h1 className="mt-2 text-2xl font-semibold text-[var(--text-primary)]">{definition?.title ?? 'Forensic Programme Analysis'}</h1><p className="mt-2 text-[11px] text-[var(--text-muted)]">Results are tied to source revision {selectedWorkspace?.source_revision.slice(0, 12) ?? '—'}.</p></div><label className="text-[9px] uppercase tracking-[.12em] text-[var(--text-muted)]">Workspace<select value={workspaceId} onChange={(e) => setSearchParams(e.target.value ? { workspace: e.target.value } : {})} className="mt-1 block min-w-[260px] border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2 text-[11px] normal-case text-[var(--text-primary)]"><option value="">No workspace selected</option>{(workspaces.data ?? []).map((workspace) => <option key={workspace.workspace_id} value={workspace.workspace_id}>{workspace.name}</option>)}</select></label></header>
          {slug === 'intake' ? <IntakePanel canEdit={canEdit} workspaceId={workspaceId} onWorkspace={(id) => setSearchParams({ workspace: id })} /> : !selectedWorkspace ? <div className="border border-[var(--border)] bg-[var(--wash)] p-6"><p className="text-[12px] text-[var(--text-secondary)]">Create or select a programme workspace before running this module.</p><Link to="/forensic/intake" className="mt-4 inline-block border border-[var(--border)] px-3 py-2 text-[10px]">Open Intake</Link></div> : <RunPanel slug={slug} workspaceId={workspaceId} programmes={selectedProgrammes} canEdit={canEdit} />}
        </div>}
      </div>
    </div>
  );
}
