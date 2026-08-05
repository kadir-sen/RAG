import apiClient from './client';
import { downloadGet } from './download';

export interface ProgrammeFile {
  file_id: string;
  name: string;
  size_bytes: number;
  sha256: string;
  created_at: string;
  duplicate?: boolean;
}

export interface ForensicWorkspace {
  workspace_id: string;
  project_id: string;
  name: string;
  programme_ids: string[];
  settings: Record<string, string | number | boolean>;
  source_revision: string;
  upstream_sha: string;
  created_at: string;
  updated_at: string;
  state_version: number;
  pipeline_version: string;
  evidence_source_ids: string[];
}

export interface ForensicProjectSource {
  source_id: string;
  source_kind: 'programme' | 'document' | 'email' | 'data';
  file_name: string;
  extension: string;
  size_bytes: number;
  content_hash: string;
  status: string;
  capabilities: string[];
  metadata: {
    title?: string;
    reference?: string;
    sheets?: string[];
    pages?: number;
    text_only?: boolean;
  };
}

export interface ForensicWorkspaceState {
  pipeline_version: string;
  baseline_programme_id: string;
  current_programme_id: string;
  contract_completion_milestone: string;
  missing_inputs: string[];
  analysis_basis: Record<string, string[]>;
  event_register: Record<string, unknown>;
  apab: Record<string, unknown>;
  umbrella: Record<string, unknown>;
  sequence: Record<string, unknown>;
  hierarchy: Record<string, unknown>;
  explain: Record<string, unknown>;
  iap: Record<string, unknown>;
  cab: Record<string, unknown>;
  narratives: Record<string, unknown>;
  report: Record<string, unknown>;
}

export interface WorkspaceStateRecord {
  workspace_id: string;
  project_id: string;
  version: number;
  state: ForensicWorkspaceState;
  created_at: string;
  updated_at: string;
}

export interface ParityControl {
  name: string;
  label: string;
  kind: string;
  default?: unknown;
  required?: boolean;
  options?: string[];
}

export interface ModuleParityContract {
  steps?: string[];
  controls: ParityControl[];
  actions: string[];
  views?: string[];
  submodules?: string[];
  artifacts?: string[];
}

export interface ForensicArtifact {
  artifact_id: string;
  run_id: string;
  kind: string;
  name: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  created_at: string;
  download_url: string;
}

export interface ResultTable {
  name: string;
  rows: Array<Record<string, unknown>>;
  total_rows: number;
  truncated: boolean;
}

export interface ForensicResult {
  title: string;
  module: string;
  metrics: Array<{ label: string; value: unknown }>;
  tables: ResultTable[];
  warnings: string[];
  caveats: string[];
  artifacts: ForensicArtifact[];
  upstream_sha: string;
  source_revision: string;
  chart?: Record<string, unknown> | null;
  narrative?: string;
  ai_status?: 'ready' | 'failed' | 'credit_balance_exhausted';
}

export interface ForensicRun {
  run_id: string;
  workspace_id: string;
  project_id: string;
  module_slug: string;
  status: 'queued' | 'processing' | 'ready' | 'failed';
  stage: string;
  progress: number;
  parameters: Record<string, unknown>;
  result: ForensicResult | null;
  error_code: string | null;
  attempt: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string;
  upstream_sha: string;
  source_revision: string;
  artifacts: ForensicArtifact[];
  traceback_id?: string | null;
}

export interface ForensicStatus {
  available: boolean;
  enabled: boolean;
  parity_available: boolean;
  parity_enabled: boolean;
  parity_validation: boolean;
  pipeline_version: string;
  parity_fingerprint: string;
  coair_sha: string;
  upstream_sha: string;
  streamlit: false;
  max_workspace_bytes: number;
  modules: Array<{ slug: string; title: string; group: string; minimum_files: number; parity: ModuleParityContract }>;
}

export async function getForensicStatus(): Promise<ForensicStatus> {
  const { data } = await apiClient.get<ForensicStatus>('/forensic/status');
  return data;
}

export async function listProgrammes(): Promise<ProgrammeFile[]> {
  const { data } = await apiClient.get<{ programmes: ProgrammeFile[] }>('/forensic/programmes');
  return data.programmes;
}

export async function listForensicSources(): Promise<ForensicProjectSource[]> {
  const { data } = await apiClient.get<{ sources: ForensicProjectSource[] }>('/forensic/sources');
  return data.sources;
}

export async function uploadProgramme(file: File): Promise<ProgrammeFile> {
  const form = new FormData();
  form.append('file', file);
  const { data } = await apiClient.post<ProgrammeFile>('/forensic/programmes', form, {
    headers: { 'Content-Type': 'multipart/form-data' }, timeout: 180_000,
  });
  return data;
}

export async function deleteProgramme(fileId: string): Promise<void> {
  await apiClient.delete(`/forensic/programmes/${fileId}`);
}

export async function listWorkspaces(): Promise<ForensicWorkspace[]> {
  const { data } = await apiClient.get<{ workspaces: ForensicWorkspace[] }>('/forensic/workspaces');
  return data.workspaces;
}

export async function createWorkspace(payload: {
  name: string;
  programme_ids: string[];
  settings?: Record<string, string | number | boolean>;
}): Promise<ForensicWorkspace> {
  const { data } = await apiClient.post<ForensicWorkspace>('/forensic/workspaces', payload);
  return data;
}

export async function updateWorkspace(
  workspaceId: string,
  payload: Partial<Pick<ForensicWorkspace, 'name' | 'programme_ids' | 'settings'>>,
): Promise<ForensicWorkspace> {
  const { data } = await apiClient.patch<ForensicWorkspace>(`/forensic/workspaces/${workspaceId}`, payload);
  return data;
}

export async function getWorkspaceState(workspaceId: string): Promise<WorkspaceStateRecord> {
  const { data } = await apiClient.get<WorkspaceStateRecord>(`/forensic/workspaces/${workspaceId}/state`);
  return data;
}

export async function patchWorkspaceState(
  workspaceId: string,
  expectedVersion: number,
  patch: Record<string, unknown>,
): Promise<WorkspaceStateRecord> {
  const { data } = await apiClient.patch<WorkspaceStateRecord>(
    `/forensic/workspaces/${workspaceId}/state`,
    { expected_version: expectedVersion, ...patch },
  );
  return data;
}

export async function replaceWorkspaceSources(
  workspaceId: string,
  expectedVersion: number,
  sourceIds: string[],
): Promise<{ workspace: ForensicWorkspace; state: WorkspaceStateRecord; sources: ForensicProjectSource[]; source_revision: string }> {
  const { data } = await apiClient.put(
    `/forensic/workspaces/${workspaceId}/sources`,
    { expected_version: expectedVersion, sources: sourceIds.map((source_id) => ({ source_id, selected_scope: {} })) },
  );
  return data;
}

export async function listForensicRuns(workspaceId = ''): Promise<ForensicRun[]> {
  const { data } = await apiClient.get<{ runs: ForensicRun[] }>('/forensic/runs', {
    params: workspaceId ? { workspace_id: workspaceId } : undefined,
  });
  return data.runs;
}

export async function createForensicRun(
  workspaceId: string,
  moduleSlug: string,
  parameters: Record<string, unknown>,
  aiNarrative = false,
): Promise<ForensicRun> {
  const { data } = await apiClient.post<ForensicRun>(
    `/forensic/workspaces/${workspaceId}/modules/${moduleSlug}/runs`,
    { parameters: { kind: moduleSlug, ...parameters }, ai_narrative: aiNarrative },
  );
  return data;
}

export async function createForensicAction<T>(
  workspaceId: string,
  moduleSlug: string,
  actionSlug: string,
  payload: Record<string, unknown>,
): Promise<T> {
  const { data } = await apiClient.post<T>(
    `/forensic/workspaces/${workspaceId}/modules/${moduleSlug}/actions/${actionSlug}`,
    { action: actionSlug, ...payload },
    { timeout: 240_000 },
  );
  return data;
}

export async function getForensicRun(runId: string): Promise<ForensicRun> {
  const { data } = await apiClient.get<ForensicRun>(`/forensic/runs/${runId}`);
  return data;
}

export async function retryForensicRun(runId: string): Promise<ForensicRun> {
  const { data } = await apiClient.post<ForensicRun>(`/forensic/runs/${runId}/retry`);
  return data;
}

export async function downloadForensicArtifact(artifact: ForensicArtifact): Promise<void> {
  await downloadGet(`/forensic/artifacts/${artifact.artifact_id}/download`, artifact.name);
}

export async function fetchForensicArtifact(artifactId: string): Promise<Blob> {
  const { data } = await apiClient.get<Blob>(`/forensic/artifacts/${artifactId}/download`, {
    responseType: 'blob',
  });
  return data;
}
