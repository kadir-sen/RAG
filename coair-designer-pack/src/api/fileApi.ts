import apiClient from './client';
import { MOCK_ENABLED } from '../mocks/adapter';
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

/**
 * Offline fallback for the "↓ CSV" / "Export" anchors.
 *
 * Those are plain `<a href>` navigations, so the axios mock adapter never
 * sees them — in designer mode the endpoint simply doesn't exist. When
 * mocking is on, build the CSV client-side from the file list the caller
 * already has (the same blob pattern SqlArtifact uses) and report `true`
 * so the click handler can preventDefault. With a real backend this is a
 * no-op and the anchor navigates as before.
 */
export function exportFilesCsvOffline(files: FileInfo[]): boolean {
  if (!MOCK_ENABLED) return false;

  const esc = (v: string | number | boolean | null) => {
    const s = String(v ?? '');
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const header = ['name', 'file_type', 'pages', 'tables', 'rows', 'notice_extracted'];
  const lines = [
    header.join(','),
    ...files.map((f) =>
      [f.name, f.file_type, f.pages ?? '', f.tables, f.rows, f.notice_extracted]
        .map(esc)
        .join(','),
    ),
  ];

  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'file_list.csv';
  a.click();
  URL.revokeObjectURL(url);
  return true;
}
