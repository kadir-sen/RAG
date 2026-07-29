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

/**
 * `fileName` is not decoration — it is what makes an old citation openable.
 * A doc_id minted before a re-ingest is an md5 of the file path at that moment,
 * so it stops resolving while the document itself is untouched on disk. The
 * name survives, and every caller already has it.
 */
export async function getDocContent(
  docId: string,
  anchor = '',
  fileName = '',
): Promise<DocContent> {
  if ((!docId || !docId.trim()) && !fileName.trim()) {
    return { type: 'text', error: 'No document ID provided' } as DocContent;
  }
  try {
    const { data } = await apiClient.get<DocContent>(
      `/docs/${encodeURIComponent(docId || fileName)}/content`,
      { params: { anchor, file_name: fileName || undefined } },
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
