import apiClient from './client';
import type {
  DataTablesStatus,
  DiagnoseResult,
  ReindexResult,
  TrustGuardStats,
} from '../types/api';

export async function getTrustGuardStats(
  days = 30,
  recent = 50,
): Promise<TrustGuardStats> {
  const { data } = await apiClient.get<TrustGuardStats>(
    '/admin/trust-guard/stats',
    { params: { days, recent } },
  );
  return data;
}

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
