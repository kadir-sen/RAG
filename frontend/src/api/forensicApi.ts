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
  coair_sha: string;
  upstream_sha: string;
  streamlit: false;
  max_workspace_bytes: number;
  modules: Array<{ slug: string; title: string; group: string; minimum_files: number }>;
}

export async function getForensicStatus(): Promise<ForensicStatus> {
  const { data } = await apiClient.get<ForensicStatus>('/forensic/status');
  return data;
}

export async function listProgrammes(): Promise<ProgrammeFile[]> {
  const { data } = await apiClient.get<{ programmes: ProgrammeFile[] }>('/forensic/programmes');
  return data.programmes;
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
