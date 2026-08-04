import apiClient from './client';

export interface ProgrammeFile {
  file_id: string;
  name: string;
  size_bytes: number;
  sha256: string;
  created_at: string;
  duplicate?: boolean;
}

export interface ToolkitLaunch {
  launch_url: string;
  expires_in_seconds: number;
  upstream_sha: string;
}

export async function listProgrammes(): Promise<ProgrammeFile[]> {
  const { data } = await apiClient.get<ProgrammeFile[]>('/toolkit/programmes');
  return data;
}

export async function uploadProgramme(file: File): Promise<ProgrammeFile> {
  const form = new FormData();
  form.append('file', file);
  const { data } = await apiClient.post<ProgrammeFile>('/toolkit/programmes', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 180_000,
  });
  return data;
}

export async function deleteProgramme(fileId: string): Promise<void> {
  await apiClient.delete(`/toolkit/programmes/${encodeURIComponent(fileId)}`);
}

export async function launchToolkit(): Promise<ToolkitLaunch> {
  const { data } = await apiClient.post<ToolkitLaunch>('/toolkit/launch');
  return data;
}
