export interface NoticeMetadata {
  date: string;
  sender: string;
  sender_company: string;
  recipient: string;
  subject: string;
  doc_type: string;
  direction: string;
  ref_numbers: string[];
  summary: string;
}

export interface Citation {
  doc_id: string;
  doc_name: string;
  anchor: string;
  snippet: string;
  score: number | null;
}

export interface RelatedDoc {
  doc_id: string;
  doc_name: string;
  date: string;
  doc_type: string;
  reason: string;
  score: number | null;
  sender: string;
  recipient: string;
}

/** How the backend suggests drawing a SQL result. Absent when it does not plot. */
export interface ChartSpec {
  type: 'bar' | 'line';
  x: string;
  y: string[];
}

export interface SQLArtifact {
  generated_sql: string;
  tables_used: string[];
  row_count: number;
  preview_rows: Record<string, unknown>[];
  source_file_id: string;
  source_file_name: string;
  chart?: ChartSpec | null;
}

export interface ProviderAnswer {
  provider: string;
  model: string;
  text: string;
  sql: string | null;
  sql_artifact: SQLArtifact | null;
}

export interface CallToAction {
  action: string;
  label: string;
  metadata: Record<string, unknown>;
}

export interface QuotaInfo {
  used_tokens: number;
  token_limit: number;
  percent_remaining: number;
  plan_type: 'legacy' | 'demo';
  credits_total: number;
  credits_remaining: number;
  credits_used: number;
  credit_percent_remaining: number;
  storage_used_bytes: number;
  storage_limit_bytes: number;
  storage_percent_used: number;
}

export interface AuthUser {
  username: string;
  display_name: string;
  role: 'user' | 'admin';
  features: Record<string, boolean>;
  token_limit: number;
  used_tokens: number;
  percent_remaining: number;
  plan_type: 'legacy' | 'demo';
  credits_total: number;
  credits_remaining: number;
  credits_used: number;
  credit_percent_remaining: number;
  storage_used_bytes: number;
  storage_limit_bytes: number;
  storage_percent_used: number;
}

export interface LoginResponse {
  access_token: string;
  token_type: 'bearer';
  user: AuthUser;
}

export interface ChatResponse {
  ui_intent: 'answer' | 'doc_list' | 'email_trace' | 'sql_result';
  assistant_text: string;
  citations: Citation[];
  related_docs: RelatedDoc[];
  sql_artifact: SQLArtifact | null;
  provider_answers: ProviderAnswer[];
  routing_confidence: number | null;
  route?: string | null;        // telemetry route: AGENT | HYBRID_COMPLEX | DOCUMENT … (observability)
  cta: CallToAction | null;
  quota: QuotaInfo | null;
}

export interface ConversationMeta {
  conversation_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  document_ids: string[];
  pinned: boolean;
  archived: boolean;
}

export interface LibraryDocument {
  doc_id: string;
  file_name: string;
  file_type: string;
  extension: string;
  status: string;
  file_size_kb: number;
  table_names: string[];
  notice_extracted: boolean;
  created_at: string;
  notice_metadata: NoticeMetadata | null;
  cluster_id?: string | null;
  cluster_label?: string | null;
}

export interface LibraryClusterSummary {
  cluster_id: string;
  label: string;
  doc_count: number;
  file_types: string[];
  sample_doc_names: string[];
}

export interface KnowledgeCollection {
  collection_id: string;
  name: string;
  description: string;
  document_ids: string[];
  document_count: number;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeCollectionDetail {
  collection_id: string;
  name: string;
  description: string;
  document_ids: string[];
  documents: LibraryDocument[];
  created_at: string;
  updated_at: string;
}

export type DataTableStatus =
  | 'registered'
  | 'no_schema_match'
  | 'error'
  | null;

export interface FileInfo {
  id: string;
  name: string;
  file_type: string;
  status: string;
  pages: number | null;
  ocr_pages: number;
  tables: number;
  rows: number;
  notice_extracted: boolean;
  data_table_status?: DataTableStatus;
  data_tables_count?: number;
  columns?: string[];
  sheets?: number;
}

export interface DataTablesStatus {
  total_data_files: number;
  registered: number;
  no_schema_match: number;
  error: number;
  pending: number;
  duckdb_tables_loaded: number;
  catalog_entries: number;
  parquet_files: number;
  schema_summary: Record<string, number>;
  files: Array<{
    file_id: string;
    file_name: string;
    extension: string;
    status: string;
    data_table_status: DataTableStatus;
    data_tables_count: number;
    table_names: string[];
  }>;
}

export interface ReindexDryRunResult {
  dry_run: true;
  total_targets: number;
  would_register: number;
  previews: Array<{
    file_id: string;
    file_name: string;
    would_register: boolean;
    reason: string | null;
    schema_matches: Array<{ sheet: string; schema_id: string; rows: number }>;
  }>;
}

export interface ReindexScheduledResult {
  dry_run: false;
  scheduled: number;
  files: string[];
}

export type ReindexResult = ReindexDryRunResult | ReindexScheduledResult;

export interface DiagnoseResult {
  ok: boolean;
  error?: string;
  file?: {
    id: string;
    name: string;
    extension: string;
    data_table_status: DataTableStatus;
  };
  extractor_matches?: Array<[string, string]> | null;
  sheets?: Array<{
    sheet: string;
    rows?: number;
    columns?: string[];
    error?: string;
    schema_matches?: Array<{
      schema_id: string;
      matched: string[];
      missing: string[];
      ratio: number;
    }>;
    best_schema?: string | null;
    best_ratio?: number;
  }>;
}

export interface UploadResult {
  file_id: string;
  filename: string;
  status: string;
}

export interface IndexingStatus {
  file_id: string;
  filename: string;
  status: 'queued' | 'extracting' | 'ocr' | 'metadata' | 'chunking' | 'embedding' | 'indexing' | 'ready' | 'failed' | 'credit_balance_exhausted' | 'unknown';
  progress: number;
  error: string | null;
  details: Record<string, unknown>;
}

export interface SchemaColumn {
  name: string;
  dtype: string;   // integer | number | date | boolean | text
  meaning: string; // jargon expansion
}

export interface DocContent {
  type: 'pdf' | 'table' | 'text';
  file_name: string;
  page: number;
  total_pages: number;
  image_base64: string;
  text: string;
  columns: string[];
  rows: Record<string, unknown>[];
  total_rows: number;
  error: string | null;
  schema_columns?: SchemaColumn[];
  description?: string;
  sheet_name?: string;
  row_from?: number | null;
  row_to?: number | null;
}

export interface ActivityStep {
  seq: number;
  ts: number;
  kind: string; // thinking | searching | reading | related | analysing | tool | answer | routing
  label: string;
  detail?: string;
}

export interface QueryProgress {
  request_id: string;
  steps: ActivityStep[];
  done: boolean;
}
