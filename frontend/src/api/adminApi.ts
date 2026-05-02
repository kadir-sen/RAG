import apiClient from './client';
import type {
  DataTablesStatus,
  DiagnoseResult,
  ReindexResult,
} from '../types/api';

export async function getDataTablesStatus(): Promise<DataTablesStatus> {
  const { data } = await apiClient.get<DataTablesStatus>(
    '/admin/data-tables/status',
  );
  return data;
}

export async function reindexDataTables(opts: {
  fileIds?: string[];
  dryRun?: boolean;
} = {}): Promise<ReindexResult> {
  const { data } = await apiClient.post<ReindexResult>(
    '/admin/data-tables/reindex',
    {
      file_ids: opts.fileIds ?? null,
      dry_run: opts.dryRun ?? false,
    },
  );
  return data;
}

export async function diagnoseDataTable(fileId: string): Promise<DiagnoseResult> {
  const { data } = await apiClient.post<DiagnoseResult>(
    '/admin/data-tables/diagnose',
    { file_id: fileId },
  );
  return data;
}
