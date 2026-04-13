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

export interface ChatResponse {
  ui_intent: 'answer' | 'doc_list' | 'email_trace' | 'sql_result';
  assistant_text: string;
  citations: Citation[];
  related_docs: RelatedDoc[];
  sql_artifact: SQLArtifact | null;
  provider_answers: ProviderAnswer[];
  routing_confidence: number | null;
}

export interface ConversationMeta {
  conversation_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  document_ids: string[];
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
}

export interface FileInfo {
  id: string;
  name: string;
  file_type: string;
  pages: number | null;
  ocr_pages: number;
  tables: number;
  rows: number;
  notice_extracted: boolean;
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
}
