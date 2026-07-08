import apiClient from './client';
import type { FileInfo, UploadResult, DocContent, IndexingStatus } from '../types/api';

export async function listFiles(): Promise<FileInfo[]> {
  const { data } = await apiClient.get<FileInfo[]>('/files');
  return data;
}

export async function uploadFile(
  file: File,
  onProgress?: (pct: number) => void,
): Promise<UploadResult> {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await apiClient.post<UploadResult>('/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (onProgress && e.total) {
        onProgress(Math.round((e.loaded * 100) / e.total));
      }
    },
  });
  return data;
}

export async function deleteFile(fileId: string) {
  await apiClient.delete(`/files/${fileId}`);
}

export async function getDocContent(
  docId: string,
  anchor = '',
): Promise<DocContent> {
  if (!docId || !docId.trim()) {
    return { type: 'text', error: 'No document ID provided' } as DocContent;
  }
  try {
    const { data } = await apiClient.get<DocContent>(
      `/docs/${encodeURIComponent(docId)}/content`,
      { params: { anchor } },
    );
    return data;
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to load document';
    return { type: 'text', error: message } as DocContent;
  }
}

export async function getIndexingStatus(): Promise<IndexingStatus[]> {
  const { data } = await apiClient.get<IndexingStatus[]>('/indexing/status');
  return data;
}

export interface DashboardStats {
  vectors: number;
  tables: number;
}

export async function getStats(): Promise<DashboardStats> {
  const { data } = await apiClient.get<DashboardStats>('/stats');
  return data;
}

export function getExportUrl(): string {
  return `${apiClient.defaults.baseURL}/files/export`;
}

/** Download a generated analysis artifact (auth header via apiClient) and
 * trigger a browser save. `url` is the server-relative path from
 * programme_artifact.artifacts[].url, e.g. "/api/artifacts/<run>/<file>". */
export async function downloadArtifact(url: string, filename: string): Promise<void> {
  const path = url.replace(/^\/api/, '');
  const { data } = await apiClient.get<Blob>(path, { responseType: 'blob' });
  const objectUrl = URL.createObjectURL(data);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objectUrl);
}
