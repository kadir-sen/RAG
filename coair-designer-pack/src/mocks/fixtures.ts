// ─────────────────────────────────────────────────────────────────────────
// Mock fixtures — realistic construction-domain sample data for COAir.
//
// These power the offline "designer mode" so the whole UI (chat, citations,
// SQL artifacts, email traces, the document viewer, the library and knowledge
// panels) renders fully without any backend. Edit freely to change the demo
// content — none of this affects production logic.
// ─────────────────────────────────────────────────────────────────────────
import type {
  AuthUser,
  ChatResponse,
  ConversationMeta,
  DocContent,
  FileInfo,
  IndexingStatus,
  KnowledgeCollection,
  KnowledgeCollectionDetail,
  LibraryDocument,
  NoticeMetadata,
} from '../types/api';
import type { UsageSnapshot } from '../api/usageApi';
import type { DashboardStats } from '../api/fileApi';
import { MOCK_PAGE_IMAGE_B64 } from './pageImage';

// ── Signed-in user ────────────────────────────────────────────────────────
export const MOCK_USER: AuthUser = {
  username: 'demo',
  display_name: 'Demo User',
  role: 'admin',
  features: { correspondence: true, document_analysis: true },
  token_limit: 1_000_000,
  used_tokens: 184_220,
  percent_remaining: 81.6,
};

// ── Notice metadata helpers ────────────────────────────────────────────────
function notice(p: Partial<NoticeMetadata>): NoticeMetadata {
  return {
    date: '2026-05-14',
    sender: 'A. Rahman',
    sender_company: 'Meydan Contracting LLC',
    recipient: 'Project Engineer',
    subject: 'Correspondence',
    doc_type: 'letter',
    direction: 'incoming',
    ref_numbers: [],
    summary: '',
    ...p,
  };
}

// ── Library documents ──────────────────────────────────────────────────────
export const LIBRARY_DOCS: LibraryDocument[] = [
  {
    doc_id: 'doc-ltr-0481',
    file_name: 'EOT_Request_Zone3_Substructure.pdf',
    file_type: 'document',
    extension: 'pdf',
    status: 'indexed',
    file_size_kb: 248,
    table_names: [],
    notice_extracted: true,
    created_at: '2026-05-14T09:12:00Z',
    cluster_id: 'cluster-eot',
    cluster_label: 'EOT & Delay',
    notice_metadata: notice({
      date: '2026-05-14',
      sender: 'A. Rahman',
      sender_company: 'Meydan Contracting LLC',
      recipient: 'Project Engineer',
      subject: 'Extension of Time — Zone 3 Substructure',
      doc_type: 'letter',
      direction: 'incoming',
      ref_numbers: ['COA-LTR-2026-0481'],
      summary:
        'Contractor requests a 21-day extension of time for the Zone 3 substructure works, citing late release of the rebar shop-drawings and an unforeseen high water table.',
    }),
  },
  {
    doc_id: 'doc-noti-0233',
    file_name: 'Delay_Notice_Concrete_Pour.pdf',
    file_type: 'document',
    extension: 'pdf',
    status: 'indexed',
    file_size_kb: 196,
    table_names: [],
    notice_extracted: true,
    created_at: '2026-05-09T07:40:00Z',
    cluster_id: 'cluster-eot',
    cluster_label: 'EOT & Delay',
    notice_metadata: notice({
      date: '2026-05-09',
      sender: 'Project Engineer',
      sender_company: 'COAir Consult',
      recipient: 'Meydan Contracting LLC',
      subject: 'Delay Notice — Concrete Pour B-12',
      doc_type: 'notice',
      direction: 'outgoing',
      ref_numbers: ['COA-NOT-2026-0233'],
      summary:
        'Engineer notifies the contractor of a 4-day slip on concrete pour B-12 caused by failed slump tests and re-batching.',
    }),
  },
  {
    doc_id: 'doc-eml-1190',
    file_name: 'RE_Rebar_Delivery_Schedule.eml',
    file_type: 'email',
    extension: 'eml',
    status: 'indexed',
    file_size_kb: 38,
    table_names: [],
    notice_extracted: true,
    created_at: '2026-05-12T14:03:00Z',
    cluster_id: 'cluster-eot',
    cluster_label: 'EOT & Delay',
    notice_metadata: notice({
      date: '2026-05-12',
      sender: 'procurement@meydan.ae',
      sender_company: 'Meydan Contracting LLC',
      recipient: 'site@coair.ae',
      subject: 'RE: Rebar Delivery Schedule — Zone 3',
      doc_type: 'email',
      direction: 'incoming',
      ref_numbers: [],
      summary:
        'Supplier confirms rebar batch 3 will arrive 5 days late; contractor flags downstream impact on the substructure pour sequence.',
    }),
  },
  {
    doc_id: 'doc-eml-1191',
    file_name: 'FW_Site_Access_Restriction.eml',
    file_type: 'email',
    extension: 'eml',
    status: 'indexed',
    file_size_kb: 29,
    table_names: [],
    notice_extracted: true,
    created_at: '2026-05-06T08:20:00Z',
    cluster_id: null,
    cluster_label: null,
    notice_metadata: notice({
      date: '2026-05-06',
      sender: 'authority@rta.gov.ae',
      sender_company: 'RTA',
      recipient: 'pm@coair.ae',
      subject: 'FW: Site Access Restriction — Gate 2',
      doc_type: 'email',
      direction: 'incoming',
      ref_numbers: [],
      summary:
        'Authority notifies a temporary access restriction at Gate 2 for two weeks affecting heavy plant movement.',
    }),
  },
  {
    doc_id: 'doc-xls-0044',
    file_name: 'Cost_Tracker_Q2_2026.xlsx',
    file_type: 'data',
    extension: 'xlsx',
    status: 'indexed',
    file_size_kb: 512,
    table_names: ['cost_tracker_q2', 'cost_by_package'],
    notice_extracted: false,
    created_at: '2026-05-13T11:00:00Z',
    cluster_id: 'cluster-cost',
    cluster_label: 'Cost & Commercial',
    notice_metadata: null,
  },
  {
    doc_id: 'doc-xls-0045',
    file_name: 'Manpower_Histogram.xlsx',
    file_type: 'data',
    extension: 'xlsx',
    status: 'indexed',
    file_size_kb: 188,
    table_names: ['manpower_weekly'],
    notice_extracted: false,
    created_at: '2026-05-11T10:15:00Z',
    cluster_id: 'cluster-cost',
    cluster_label: 'Cost & Commercial',
    notice_metadata: null,
  },
  {
    doc_id: 'doc-rpt-0512',
    file_name: 'Daily_Progress_Report_2026-05-12.pdf',
    file_type: 'document',
    extension: 'pdf',
    status: 'indexed',
    file_size_kb: 320,
    table_names: [],
    notice_extracted: true,
    created_at: '2026-05-12T18:30:00Z',
    cluster_id: null,
    cluster_label: null,
    notice_metadata: notice({
      date: '2026-05-12',
      sender: 'Site Team',
      sender_company: 'Meydan Contracting LLC',
      recipient: 'Project Engineer',
      subject: 'Daily Progress Report — 12 May 2026',
      doc_type: 'dpr',
      direction: 'incoming',
      ref_numbers: ['DPR-2026-05-12'],
      summary:
        'Substructure rebar fixing 62% complete; two tower cranes operational; 184 workers on site.',
    }),
  },
  {
    doc_id: 'doc-con-0001',
    file_name: 'Main_Contract_Conditions.pdf',
    file_type: 'document',
    extension: 'pdf',
    status: 'indexed',
    file_size_kb: 1840,
    table_names: [],
    notice_extracted: true,
    created_at: '2026-03-02T09:00:00Z',
    cluster_id: null,
    cluster_label: null,
    notice_metadata: notice({
      date: '2026-03-02',
      sender: 'Employer',
      sender_company: 'Dubai Holding',
      recipient: 'Meydan Contracting LLC',
      subject: 'Main Contract — Conditions of Contract',
      doc_type: 'contract',
      direction: 'incoming',
      ref_numbers: ['MC-2026-001'],
      summary:
        'FIDIC-based conditions of contract. Clause 8.4 governs extension of time; Clause 20.1 governs contractor claims.',
    }),
  },
];

const byId = (id: string) => LIBRARY_DOCS.find((d) => d.doc_id === id)!;

// ── Library summary (welcome-screen KPIs) ──────────────────────────────────
export const LIBRARY_SUMMARY = {
  total_files: LIBRARY_DOCS.length,
  total_tables: 3,
  by_file_type: { pdf: 4, eml: 2, xlsx: 2 },
  by_doc_type: {
    letter: 1,
    notice: 1,
    email: 2,
    dpr: 1,
    contract: 1,
    data_file: 2,
  },
};

// ── Files panel (LeftDrawer) ───────────────────────────────────────────────
export const FILES: FileInfo[] = [
  { id: 'doc-ltr-0481', name: 'EOT_Request_Zone3_Substructure.pdf', file_type: 'pdf', pages: 4, ocr_pages: 0, tables: 0, rows: 0, notice_extracted: true },
  { id: 'doc-noti-0233', name: 'Delay_Notice_Concrete_Pour.pdf', file_type: 'pdf', pages: 2, ocr_pages: 0, tables: 0, rows: 0, notice_extracted: true },
  { id: 'doc-eml-1190', name: 'RE_Rebar_Delivery_Schedule.eml', file_type: 'eml', pages: null, ocr_pages: 0, tables: 0, rows: 0, notice_extracted: true },
  { id: 'doc-eml-1191', name: 'FW_Site_Access_Restriction.eml', file_type: 'eml', pages: null, ocr_pages: 0, tables: 0, rows: 0, notice_extracted: true },
  { id: 'doc-xls-0044', name: 'Cost_Tracker_Q2_2026.xlsx', file_type: 'xlsx', pages: null, ocr_pages: 0, tables: 2, rows: 142, notice_extracted: false, data_table_status: 'registered', data_tables_count: 2 },
  { id: 'doc-xls-0045', name: 'Manpower_Histogram.xlsx', file_type: 'xlsx', pages: null, ocr_pages: 0, tables: 1, rows: 26, notice_extracted: false, data_table_status: 'registered', data_tables_count: 1 },
  { id: 'doc-rpt-0512', name: 'Daily_Progress_Report_2026-05-12.pdf', file_type: 'pdf', pages: 3, ocr_pages: 1, tables: 0, rows: 0, notice_extracted: true },
  { id: 'doc-con-0001', name: 'Main_Contract_Conditions.pdf', file_type: 'pdf', pages: 96, ocr_pages: 0, tables: 0, rows: 0, notice_extracted: true },
];

export const STATS: DashboardStats = { vectors: 4128, tables: 3 };

export const INDEXING_STATUS: IndexingStatus[] = [
  { file_id: 'doc-xls-0045', filename: 'Manpower_Histogram.xlsx', status: 'completed', progress: 100, error: null, details: {} },
  { file_id: 'doc-rpt-0512', filename: 'Daily_Progress_Report_2026-05-12.pdf', status: 'completed', progress: 100, error: null, details: {} },
];

// ── Usage snapshot (TopNav badge / settings) ───────────────────────────────
export const USAGE: UsageSnapshot = {
  used_usd: 12.84,
  limit_usd: 50,
  remaining_usd: 37.16,
  remaining_pct: 74.3,
  over_budget: false,
  prompt_tokens: 142_880,
  completion_tokens: 41_340,
  total_tokens: 184_220,
  total_calls: 312,
};

// ── Chat answer building blocks ────────────────────────────────────────────
const EOT_ANSWER: ChatResponse = {
  ui_intent: 'answer',
  assistant_text:
    "The contractor's entitlement to an Extension of Time for the Zone 3 substructure rests on two concurrent causes:\n\n" +
    '1. **Late rebar shop-drawing release** — Batch 3 was confirmed 5 days late by the supplier, delaying the substructure pour sequence.\n' +
    '2. **Unforeseen high water table** — site dewatering added an estimated 9 days to the excavation.\n\n' +
    'Per **Clause 8.4** of the Conditions of Contract, both are compensable grounds. The Engineer has separately issued a Delay Notice (COA-NOT-2026-0233) acknowledging a 4-day slip on pour B-12, which overlaps the claimed period. Net recommended EOT: **14 days** (concurrent delay deducted).',
  citations: [
    { doc_id: 'doc-ltr-0481', doc_name: 'EOT_Request_Zone3_Substructure.pdf', anchor: 'page_1', snippet: 'request a 21-day extension of time for the Zone 3 substructure works…', score: 0.91 },
    { doc_id: 'doc-con-0001', doc_name: 'Main_Contract_Conditions.pdf', anchor: 'page_24', snippet: 'Clause 8.4 — the Contractor shall be entitled to an Extension of Time if completion is delayed by…', score: 0.86 },
    { doc_id: 'doc-noti-0233', doc_name: 'Delay_Notice_Concrete_Pour.pdf', anchor: 'page_1', snippet: 'a 4-day slip on concrete pour B-12 caused by failed slump tests…', score: 0.79 },
  ],
  related_docs: [
    { doc_id: 'doc-eml-1190', doc_name: 'RE_Rebar_Delivery_Schedule.eml', date: '2026-05-12', doc_type: 'email', reason: 'Confirms the 5-day rebar delivery slip cited in the claim', score: 0.74, sender: 'procurement@meydan.ae', recipient: 'site@coair.ae' },
    { doc_id: 'doc-rpt-0512', doc_name: 'Daily_Progress_Report_2026-05-12.pdf', date: '2026-05-12', doc_type: 'dpr', reason: 'Records 62% rebar-fixing progress on the affected zone', score: 0.68, sender: 'Site Team', recipient: 'Project Engineer' },
  ],
  sql_artifact: null,
  provider_answers: [],
  routing_confidence: 0.88,
  cta: null,
  quota: { used_tokens: 184_220, token_limit: 1_000_000, percent_remaining: 81.6 },
};

const COST_SQL_ANSWER: ChatResponse = {
  ui_intent: 'sql_result',
  assistant_text:
    'The Q2 cost overrun is concentrated in two packages. **Substructure** is **AED 1.42M over budget** (+18.4%) and **MEP first-fix** is **AED 0.61M over** (+7.2%). All other packages are within tolerance.',
  citations: [],
  related_docs: [],
  sql_artifact: {
    generated_sql:
      "SELECT package,\n       budget_aed,\n       actual_aed,\n       actual_aed - budget_aed AS variance_aed,\n       ROUND(100.0 * (actual_aed - budget_aed) / budget_aed, 1) AS variance_pct\nFROM cost_tracker_q2\nWHERE actual_aed > budget_aed\nORDER BY variance_aed DESC;",
    tables_used: ['cost_tracker_q2'],
    row_count: 4,
    preview_rows: [
      { package: 'Substructure', budget_aed: 7_720_000, actual_aed: 9_140_000, variance_aed: 1_420_000, variance_pct: 18.4 },
      { package: 'MEP First Fix', budget_aed: 8_480_000, actual_aed: 9_090_000, variance_aed: 610_000, variance_pct: 7.2 },
      { package: 'Façade', budget_aed: 6_200_000, actual_aed: 6_350_000, variance_aed: 150_000, variance_pct: 2.4 },
      { package: 'Fit-out', budget_aed: 5_100_000, actual_aed: 5_180_000, variance_aed: 80_000, variance_pct: 1.6 },
    ],
    source_file_id: 'doc-xls-0044',
    source_file_name: 'Cost_Tracker_Q2_2026.xlsx',
  },
  provider_answers: [],
  routing_confidence: 0.93,
  cta: null,
  quota: { used_tokens: 184_220, token_limit: 1_000_000, percent_remaining: 81.6 },
};

const EMAIL_TRACE_ANSWER: ChatResponse = {
  ui_intent: 'email_trace',
  assistant_text:
    'Here is the correspondence thread on the Zone 3 rebar delivery. The supplier confirmed a 5-day slip on Batch 3, which the contractor later folded into the EOT request.',
  citations: [
    { doc_id: 'doc-eml-1190', doc_name: 'RE_Rebar_Delivery_Schedule.eml', anchor: '', snippet: 'Batch 3 will now arrive on 17 May, five days later than scheduled…', score: 0.9 },
  ],
  related_docs: [
    { doc_id: 'doc-ltr-0481', doc_name: 'EOT_Request_Zone3_Substructure.pdf', date: '2026-05-14', doc_type: 'letter', reason: 'Cites this delivery slip as a ground for the time extension', score: 0.81, sender: 'A. Rahman', recipient: 'Project Engineer' },
  ],
  sql_artifact: null,
  provider_answers: [],
  routing_confidence: 0.84,
  cta: null,
  quota: { used_tokens: 184_220, token_limit: 1_000_000, percent_remaining: 81.6 },
};

// Default canned answer for any new message the designer sends.
export const DEFAULT_CHAT_ANSWER = EOT_ANSWER;

// Keyed answers used by the chat route to vary the response by intent.
export const CHAT_ANSWERS = {
  eot: EOT_ANSWER,
  cost: COST_SQL_ANSWER,
  emailTrace: EMAIL_TRACE_ANSWER,
};

// Admin → data-tables status panel.
export const COST_TABLE_PLACEHOLDER = {
  total_data_files: 2,
  registered: 2,
  no_schema_match: 0,
  error: 0,
  pending: 0,
  duckdb_tables_loaded: 3,
  catalog_entries: 3,
  parquet_files: 3,
  schema_summary: { cost_tracker: 1, manpower: 1 },
  files: [
    { file_id: 'doc-xls-0044', file_name: 'Cost_Tracker_Q2_2026.xlsx', extension: 'xlsx', status: 'indexed', data_table_status: 'registered' as const, data_tables_count: 2, table_names: ['cost_tracker_q2', 'cost_by_package'] },
    { file_id: 'doc-xls-0045', file_name: 'Manpower_Histogram.xlsx', extension: 'xlsx', status: 'indexed', data_table_status: 'registered' as const, data_tables_count: 1, table_names: ['manpower_weekly'] },
  ],
};

// ── Conversations ──────────────────────────────────────────────────────────
export const CONVERSATIONS: ConversationMeta[] = [
  { conversation_id: 'conv-1', title: 'EOT entitlement — Zone 3 substructure', created_at: '2026-05-14T09:20:00Z', updated_at: '2026-05-14T09:24:00Z', message_count: 2, document_ids: ['doc-ltr-0481', 'doc-con-0001', 'doc-noti-0233'], pinned: true, archived: false },
  { conversation_id: 'conv-2', title: 'Q2 cost overrun by package', created_at: '2026-05-13T13:02:00Z', updated_at: '2026-05-13T13:05:00Z', message_count: 2, document_ids: ['doc-xls-0044'], pinned: false, archived: false },
  { conversation_id: 'conv-3', title: 'Rebar delivery correspondence', created_at: '2026-05-12T15:10:00Z', updated_at: '2026-05-12T15:12:00Z', message_count: 2, document_ids: ['doc-eml-1190'], pinned: false, archived: false },
  { conversation_id: 'conv-4', title: 'Gate 2 access restriction', created_at: '2026-05-06T08:40:00Z', updated_at: '2026-05-06T08:41:00Z', message_count: 2, document_ids: ['doc-eml-1191'], pinned: false, archived: false },
];

interface StoredMsg { role: 'user' | 'assistant'; content: string; timestamp: string; response?: ChatResponse }
interface ConvDetail { conversation_id: string; title: string; document_ids: string[]; messages: StoredMsg[] }

export const CONVERSATION_DETAIL: Record<string, ConvDetail> = {
  'conv-1': {
    conversation_id: 'conv-1',
    title: 'EOT entitlement — Zone 3 substructure',
    document_ids: ['doc-ltr-0481', 'doc-con-0001', 'doc-noti-0233'],
    messages: [
      { role: 'user', content: 'Is the contractor entitled to an extension of time for the Zone 3 substructure? Summarise the grounds and cite the clause.', timestamp: '2026-05-14T09:20:00Z' },
      { role: 'assistant', content: EOT_ANSWER.assistant_text, timestamp: '2026-05-14T09:24:00Z', response: EOT_ANSWER },
    ],
  },
  'conv-2': {
    conversation_id: 'conv-2',
    title: 'Q2 cost overrun by package',
    document_ids: ['doc-xls-0044'],
    messages: [
      { role: 'user', content: 'Which packages are over budget in Q2 and by how much?', timestamp: '2026-05-13T13:02:00Z' },
      { role: 'assistant', content: COST_SQL_ANSWER.assistant_text, timestamp: '2026-05-13T13:05:00Z', response: COST_SQL_ANSWER },
    ],
  },
  'conv-3': {
    conversation_id: 'conv-3',
    title: 'Rebar delivery correspondence',
    document_ids: ['doc-eml-1190'],
    messages: [
      { role: 'user', content: 'Trace the rebar delivery email thread for Zone 3.', timestamp: '2026-05-12T15:10:00Z' },
      { role: 'assistant', content: EMAIL_TRACE_ANSWER.assistant_text, timestamp: '2026-05-12T15:12:00Z', response: EMAIL_TRACE_ANSWER },
    ],
  },
  'conv-4': {
    conversation_id: 'conv-4',
    title: 'Gate 2 access restriction',
    document_ids: ['doc-eml-1191'],
    messages: [
      { role: 'user', content: 'What does the RTA notice say about Gate 2 access?', timestamp: '2026-05-06T08:40:00Z' },
      {
        role: 'assistant',
        content: 'The RTA has imposed a temporary access restriction at Gate 2 for two weeks, affecting heavy plant movement. Re-route deliveries via Gate 4 and rephase crane lifts accordingly.',
        timestamp: '2026-05-06T08:41:00Z',
        response: {
          ui_intent: 'answer',
          assistant_text: 'The RTA has imposed a temporary access restriction at Gate 2 for two weeks, affecting heavy plant movement. Re-route deliveries via Gate 4 and rephase crane lifts accordingly.',
          citations: [
            { doc_id: 'doc-eml-1191', doc_name: 'FW_Site_Access_Restriction.eml', anchor: '', snippet: 'temporary access restriction at Gate 2 for a period of two weeks…', score: 0.88 },
          ],
          related_docs: [],
          sql_artifact: null,
          provider_answers: [],
          routing_confidence: 0.8,
          cta: null,
          quota: null,
        },
      },
    ],
  },
};

// ── Knowledge collections ──────────────────────────────────────────────────
export const KNOWLEDGE: KnowledgeCollection[] = [
  { collection_id: 'kc-eot', name: 'EOT & Delay Claims', description: 'Notices, letters and DPRs supporting the Zone 3 time-extension claim.', document_ids: ['doc-ltr-0481', 'doc-noti-0233', 'doc-eml-1190', 'doc-rpt-0512'], document_count: 4, created_at: '2026-05-10T09:00:00Z', updated_at: '2026-05-14T09:30:00Z' },
  { collection_id: 'kc-cost', name: 'Q2 Commercial', description: 'Cost trackers and manpower data for the Q2 commercial review.', document_ids: ['doc-xls-0044', 'doc-xls-0045'], document_count: 2, created_at: '2026-05-11T10:00:00Z', updated_at: '2026-05-13T11:10:00Z' },
];

export const KNOWLEDGE_DETAIL: Record<string, KnowledgeCollectionDetail> = {
  'kc-eot': {
    collection_id: 'kc-eot',
    name: 'EOT & Delay Claims',
    description: 'Notices, letters and DPRs supporting the Zone 3 time-extension claim.',
    document_ids: ['doc-ltr-0481', 'doc-noti-0233', 'doc-eml-1190', 'doc-rpt-0512'],
    documents: ['doc-ltr-0481', 'doc-noti-0233', 'doc-eml-1190', 'doc-rpt-0512'].map(byId),
    created_at: '2026-05-10T09:00:00Z',
    updated_at: '2026-05-14T09:30:00Z',
  },
  'kc-cost': {
    collection_id: 'kc-cost',
    name: 'Q2 Commercial',
    description: 'Cost trackers and manpower data for the Q2 commercial review.',
    document_ids: ['doc-xls-0044', 'doc-xls-0045'],
    documents: ['doc-xls-0044', 'doc-xls-0045'].map(byId),
    created_at: '2026-05-11T10:00:00Z',
    updated_at: '2026-05-13T11:10:00Z',
  },
};

// ── Document viewer content ────────────────────────────────────────────────
const COST_TABLE_ROWS: Record<string, unknown>[] = [
  { package: 'Substructure', budget_aed: 7_720_000, actual_aed: 9_140_000, variance_aed: 1_420_000, variance_pct: 18.4 },
  { package: 'MEP First Fix', budget_aed: 8_480_000, actual_aed: 9_090_000, variance_aed: 610_000, variance_pct: 7.2 },
  { package: 'Façade', budget_aed: 6_200_000, actual_aed: 6_350_000, variance_aed: 150_000, variance_pct: 2.4 },
  { package: 'Fit-out', budget_aed: 5_100_000, actual_aed: 5_180_000, variance_aed: 80_000, variance_pct: 1.6 },
  { package: 'Earthworks', budget_aed: 3_400_000, actual_aed: 3_310_000, variance_aed: -90_000, variance_pct: -2.6 },
  { package: 'Piling', budget_aed: 4_900_000, actual_aed: 4_820_000, variance_aed: -80_000, variance_pct: -1.6 },
];

const EMAIL_TEXT_1190 =
  'From: procurement@meydan.ae\n' +
  'To: site@coair.ae\n' +
  'Date: 12 May 2026, 14:03\n' +
  'Subject: RE: Rebar Delivery Schedule — Zone 3\n\n' +
  'Dear Site Team,\n\n' +
  'Following up on our call — the mill has confirmed that Batch 3 (T20 / T25, ~62t) ' +
  'will now arrive on 17 May, five days later than the scheduled 12 May. The delay is ' +
  'due to a rolling-mill changeover at the supplier.\n\n' +
  'We understand this pushes the substructure pour sequence for Zone 3. Please advise if ' +
  'you want us to prioritise the T25 bundles for the pile caps so fixing can start ahead ' +
  'of the slab reinforcement.\n\n' +
  'Best regards,\nProcurement — Meydan Contracting LLC';

function pdfContent(fileName: string, pages: number): DocContent {
  return {
    type: 'pdf', file_name: fileName, page: 1, total_pages: pages,
    image_base64: MOCK_PAGE_IMAGE_B64, text: '', columns: [], rows: [], total_rows: 0, error: null,
  };
}

export const DOC_CONTENT: Record<string, DocContent> = {
  'doc-ltr-0481': pdfContent('EOT_Request_Zone3_Substructure.pdf', 4),
  'doc-noti-0233': pdfContent('Delay_Notice_Concrete_Pour.pdf', 2),
  'doc-rpt-0512': pdfContent('Daily_Progress_Report_2026-05-12.pdf', 3),
  'doc-con-0001': pdfContent('Main_Contract_Conditions.pdf', 96),
  'doc-xls-0044': {
    type: 'table', file_name: 'Cost_Tracker_Q2_2026.xlsx', page: 1, total_pages: 1,
    image_base64: '', text: '',
    columns: ['package', 'budget_aed', 'actual_aed', 'variance_aed', 'variance_pct'],
    rows: COST_TABLE_ROWS, total_rows: COST_TABLE_ROWS.length, error: null,
  },
  'doc-xls-0045': {
    type: 'table', file_name: 'Manpower_Histogram.xlsx', page: 1, total_pages: 1,
    image_base64: '', text: '',
    columns: ['week', 'planned', 'actual'],
    rows: [
      { week: 'W18', planned: 160, actual: 152 },
      { week: 'W19', planned: 175, actual: 168 },
      { week: 'W20', planned: 190, actual: 184 },
      { week: 'W21', planned: 200, actual: 171 },
    ],
    total_rows: 4, error: null,
  },
  'doc-eml-1190': {
    type: 'text', file_name: 'RE_Rebar_Delivery_Schedule.eml', page: 1, total_pages: 1,
    image_base64: '', text: EMAIL_TEXT_1190, columns: [], rows: [], total_rows: 0, error: null,
  },
  'doc-eml-1191': {
    type: 'text', file_name: 'FW_Site_Access_Restriction.eml', page: 1, total_pages: 1,
    image_base64: '', text:
      'From: authority@rta.gov.ae\nTo: pm@coair.ae\nDate: 6 May 2026, 08:20\n' +
      'Subject: FW: Site Access Restriction — Gate 2\n\n' +
      'This is to notify a temporary access restriction at Gate 2 for a period of two weeks, ' +
      'effective 8 May, in connection with adjacent road works. Heavy plant movement must be ' +
      're-routed via Gate 4. Coordinate crane-lift timings with the site marshal.',
    columns: [], rows: [], total_rows: 0, error: null,
  },
};

export function docContentFor(docId: string): DocContent {
  return (
    DOC_CONTENT[docId] ?? {
      type: 'text', file_name: docId, page: 1, total_pages: 1, image_base64: '',
      text: 'No preview available for this document in designer mode.',
      columns: [], rows: [], total_rows: 0, error: null,
    }
  );
}
