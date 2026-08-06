import apiClient from './client';
import { downloadGet } from './download';

export interface ReportJob {
  job_id: string;
  project_id: string;
  module: 'chronology' | 'forensic';
  title: string;
  status: 'queued' | 'processing' | 'ready' | 'failed' | 'credit_balance_exhausted';
  stage: string;
  progress: number;
  error: string | null;
  error_code?: string | null;
  retryable?: boolean;
  pipeline_version?: string;
  coverage_status?: string | null;
  result: Record<string, unknown> | null;
  created_at: string;
  sequence_number: number | null;
  report_url?: string;
}

export interface ChronologySourceDocument {
  doc_id: string;
  /** Every stored fragment of this document. A row is one document; the corpus
      splits one file into ~14 doc_ids, so the fragments are listed rather than
      each becoming its own row. */
  doc_ids: string[];
  file_name: string;
  /** Best matching passage, not the sum over passages — summing ranked long
      documents above precise ones. */
  score: number;
  pages: number[];
  source_count: number;
  selected: boolean;
  /** Characters of this document that fit the evidence budget. */
  selected_chars: number;
}

export interface ChronologySourcePreview {
  preparation_id: string;
  expires_at: string;
  documents: ChronologySourceDocument[];
  /** Measured over the pack that would actually be read, not over everything
      retrieval surfaced. */
  coverage: Record<string, number>;
  coverage_status: 'complete' | 'partial';
  selection?: Record<string, number>;
}

export interface ToolkitArtifact {
  artifact_id: string;
  title: string;
  methodology: string;
  findings: string[];
}

export async function generateReport(
  module: 'chronology' | 'forensic',
  payload: Record<string, unknown>,
): Promise<ReportJob> {
  const { data } = await apiClient.post<ReportJob>(`/${module}/generate`, payload);
  return data;
}

export async function listReports(module: 'chronology' | 'forensic'): Promise<ReportJob[]> {
  const { data } = await apiClient.get<{ reports: ReportJob[] }>('/reports', { params: { module } });
  return data.reports;
}

export async function previewChronologySources(
  payload: Record<string, unknown>,
): Promise<ChronologySourcePreview> {
  const { data } = await apiClient.post<ChronologySourcePreview>('/chronology/source-preview', payload);
  return data;
}

export async function retryReport(jobId: string): Promise<ReportJob> {
  const { data } = await apiClient.post<ReportJob>(`/reports/${jobId}/retry`);
  return data;
}

export async function getReport(jobId: string): Promise<ReportJob> {
  const { data } = await apiClient.get<ReportJob>(`/reports/${jobId}`);
  return data;
}

export interface ResolvedReportSource {
  source: Record<string, unknown>;
  record: { doc_id?: string; file_name?: string; page?: number; status: string };
}

export async function resolveReportSource(jobId: string, sourceId: string): Promise<ResolvedReportSource> {
  const { data } = await apiClient.get<ResolvedReportSource>(`/reports/${jobId}/sources/${sourceId}`);
  return data;
}

export async function saveForensicDraft(
  jobId: string,
  sections: Record<string, Array<Record<string, unknown>>>,
  issue = false,
): Promise<ReportJob> {
  const { data } = await apiClient.patch<ReportJob>(`/reports/${jobId}/draft`, { sections, issue });
  return data;
}

export async function listToolkitEvidence(): Promise<ToolkitArtifact[]> {
  const { data } = await apiClient.get<{ artifacts: ToolkitArtifact[] }>('/forensic/toolkit-evidence');
  return data.artifacts;
}

export async function downloadReport(job: ReportJob): Promise<void> {
  await downloadGet(`/reports/${job.job_id}/document`, `${job.module}-${job.title}.docx`);
}
