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

export interface SQLArtifact {
  generated_sql: string;
  tables_used: string[];
  row_count: number;
  preview_rows: Record<string, unknown>[];
  source_file_id: string;
  source_file_name: string;
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
}

export interface AuthUser {
  username: string;
  display_name: string;
  role: 'user' | 'admin';
  features: Record<string, boolean>;
  token_limit: number;
  used_tokens: number;
  percent_remaining: number;
}

export interface LoginResponse {
  access_token: string;
  token_type: 'bearer';
  user: AuthUser;
}

// ── Programme analysis (deterministic XER tools) ─────────────

export interface ProgrammeTable {
  title: string;
  columns: string[];
  rows: (string | number | null)[][];
  caption?: string;
}

export interface ProgrammeChartPoint {
  x: string;            // ISO date
  y: string | number | null;
  marker?: string | null;
}

export interface ProgrammeChart {
  chart_id: string;
  type: string;         // "line"
  title: string;
  x_label?: string;
  y_label?: string;
  series: { name: string; points: ProgrammeChartPoint[] }[];
}

export interface ProgrammeArtifactFile {
  artifact_id: string;
  kind: string;
  filename: string;
  url: string;
}

export interface ProgrammeValidation {
  computation_guard?: {
    pre?: 'passed' | 'failed';
    post?: 'passed' | 'violations';
    violations?: string[];
  };
  narrative_guard?: {
    status:
      | 'approved'
      | 'rewritten_then_approved'
      | 'fallback_after_rejection'
      | 'llm_unavailable'
      | 'deterministic_only';
    violations?: string[];
  };
}

export interface ProgrammeToolResult {
  tool_id: string;
  status: 'complete' | 'partial' | 'failed';
  summary: string;
  tables: ProgrammeTable[];
  charts: ProgrammeChart[];
  artifacts: ProgrammeArtifactFile[];
  warnings: string[];
  caveats: string[];
  requires_analyst_review: boolean;
  validation?: ProgrammeValidation;
}

export interface ProgrammePackSection {
  section_id: string;
  title: string;
  tool_result: ProgrammeToolResult | null;
  narrative: string;
}

/** Either a single ToolResult or a workflow pack (has `sections`). */
export interface ProgrammeArtifact extends Partial<ProgrammeToolResult> {
  pack_id?: string;
  workflow_id?: string;
  sections?: ProgrammePackSection[];
}

export interface TrustGuardRun {
  ts: string;
  username: string;
  query: string;
  route: string;
  risk: string;
  action: string;
  sufficiency: number;
  latency_ms: number;
  skipped: boolean;
  skipped_reason: string;
}

export interface TrustGuardStats {
  ok: boolean;
  total_runs: number;
  guarded: number;
  skipped: number;
  coverage_pct: number;
  actions: Record<string, number>;
  skip_reasons: Record<string, number>;
  risk: Record<string, number>;
  avg_latency_ms: number;
  p95_latency_ms: number;
  avg_llm_calls: number;
  catches: {
    unknown_entity_runs: number;
    re_retrievals: number;
    rewrites_or_refusals: number;
  };
  recent: TrustGuardRun[];
}

// ── Chat-native response blocks ──────────────────────────────

export interface MarkdownTextBlock {
  type: 'markdown_text';
  block_id: string;
  text: string;
}

export interface DataTableBlock {
  type: 'data_table';
  block_id: string;
  title: string;
  columns: string[];
  rows: (string | number | null)[][];
  caption?: string;
}

export interface ChartBlockData {
  type: 'chart';
  block_id: string;
  chart_type: 'line' | 'bar';
  title: string;
  x_label?: string;
  y_label?: string;
  series?: { name: string; points: { x: string | number; y: string | number | null; marker?: string | null }[] }[] | null;
  categories?: string[] | null;
  values?: number[] | null;
}

export interface HtmlReportSectionBlock {
  type: 'html_report_section';
  block_id: string;
  title: string;
  html: string;
  fallback_markdown: string;
  sanitized: true;
}

export interface ArtifactLinkBlock {
  type: 'artifact_link';
  block_id: string;
  url: string;
  filename: string;
  kind: string;
}

export interface CaveatsBlockData {
  type: 'caveats';
  block_id: string;
  caveats: string[];
  warnings: string[];
}

export interface ValidationStatusBlock {
  type: 'validation_status';
  block_id: string;
  guards: Record<string, 'passed' | 'failed' | 'fallback' | 'skipped'>;
  requires_analyst_review: boolean;
  fallbacks_used: string[];
}

export interface ClarificationBlockData {
  type: 'clarification';
  block_id: string;
  question: string;
  options: { label: string; value: string }[];
}

export type ChatBlock =
  | MarkdownTextBlock
  | DataTableBlock
  | ChartBlockData
  | HtmlReportSectionBlock
  | ArtifactLinkBlock
  | CaveatsBlockData
  | ValidationStatusBlock
  | ClarificationBlockData;

export interface TrustGuardInfo {
  sufficiency_label: 'verified' | 'partially_supported' | 'insufficient' | 'unverified' | '';
  sufficiency: number; // 0..1
  caveats: string[];
  analyst_review_required: boolean;
  action: 'approve' | 'approve_with_caveats' | 'rewrite' | 'refuse' | '';
}

export interface ChatResponse {
  ui_intent: 'answer' | 'doc_list' | 'timeline' | 'email_trace' | 'sql_result' | 'programme_result' | 'blocks';
  assistant_text: string;
  citations: Citation[];
  related_docs: RelatedDoc[];
  sql_artifact: SQLArtifact | null;
  provider_answers: ProviderAnswer[];
  routing_confidence: number | null;
  route?: string | null;        // telemetry route: AGENT | HYBRID_COMPLEX | DOCUMENT … (observability)
  cta: CallToAction | null;
  quota: QuotaInfo | null;
  trust_guard?: TrustGuardInfo | null;
  programme_artifact?: ProgrammeArtifact | null;
  blocks?: ChatBlock[] | null;
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
  status: 'pending' | 'indexing' | 'completed' | 'error';
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
