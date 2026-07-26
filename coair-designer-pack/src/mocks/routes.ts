// ─────────────────────────────────────────────────────────────────────────
// Mock route table. Each entry matches an HTTP method + a URL path pattern and
// returns the response body. The first matching entry wins, so more specific
// paths are listed before their generic siblings (e.g. /library/summary before
// /library/:id). Everything here is plain data — see fixtures.ts to edit it.
// ─────────────────────────────────────────────────────────────────────────
import {
  CONVERSATIONS,
  CONVERSATION_DETAIL,
  COST_TABLE_PLACEHOLDER,
  DEFAULT_CHAT_ANSWER,
  FILES,
  INDEXING_STATUS,
  KNOWLEDGE,
  KNOWLEDGE_DETAIL,
  LIBRARY_DOCS,
  LIBRARY_SUMMARY,
  MOCK_USER,
  STATS,
  USAGE,
  docContentFor,
} from './fixtures';
import {
  CHAT_ANSWERS,
} from './fixtures';

export interface MockCtx {
  params: string[]; // regex capture groups
  query: URLSearchParams;
  body: unknown; // parsed JSON body (or undefined / FormData)
}

interface Route {
  method: string;
  pattern: RegExp;
  handler: (ctx: MockCtx) => unknown;
}

const ok = (data: unknown) => data;
const docsByIds = (ids: string[]) =>
  ids.map((id) => LIBRARY_DOCS.find((d) => d.doc_id === id)).filter(Boolean);

// Pick a canned answer based on what the user typed, so a designer sending a
// message sees a relevant response surface (plain answer / SQL / email trace).
function chatAnswerFor(body: unknown) {
  const msg = String((body as { message?: string })?.message ?? '').toLowerCase();
  if (/cost|budget|overrun|variance|aed|over budget/.test(msg)) return CHAT_ANSWERS.cost;
  if (/email|thread|correspondence|trace|rebar/.test(msg)) return CHAT_ANSWERS.emailTrace;
  return DEFAULT_CHAT_ANSWER;
}

export const ROUTES: Route[] = [
  // ── Auth (accepts any credentials in designer mode) ──────────────────────
  { method: 'POST', pattern: /^\/auth\/login$/, handler: () => ({
      access_token: 'designer-mock-token', token_type: 'bearer', user: MOCK_USER,
    }) },
  { method: 'GET', pattern: /^\/auth\/me$/, handler: () => ({ user: MOCK_USER }) },
  { method: 'POST', pattern: /^\/auth\/logout$/, handler: () => ({ ok: true }) },

  // ── Conversations (specific paths first) ─────────────────────────────────
  { method: 'GET', pattern: /^\/conversations\/([^/]+)\/documents$/, handler: ({ params }) =>
      docsByIds(CONVERSATION_DETAIL[params[0]]?.document_ids ?? []) },
  { method: 'POST', pattern: /^\/conversations\/([^/]+)\/documents$/, handler: ({ body }) =>
      ({ ok: true, document_ids: (body as { doc_ids?: string[] })?.doc_ids ?? [] }) },
  { method: 'DELETE', pattern: /^\/conversations\/([^/]+)\/documents\/([^/]+)$/, handler: () => ({ ok: true }) },
  { method: 'PATCH', pattern: /^\/conversations\/([^/]+)\/pin$/, handler: ({ params, body }) => {
      const c = CONVERSATIONS.find((x) => x.conversation_id === params[0]);
      return { ...c, pinned: Boolean((body as { pinned?: boolean })?.pinned) };
    } },
  { method: 'PATCH', pattern: /^\/conversations\/([^/]+)\/archive$/, handler: ({ params, body }) => {
      const c = CONVERSATIONS.find((x) => x.conversation_id === params[0]);
      return { ...c, archived: Boolean((body as { archived?: boolean })?.archived) };
    } },
  { method: 'GET', pattern: /^\/conversations$/, handler: ({ query }) => {
      const archived = query.get('archived') === 'true';
      return CONVERSATIONS.filter((c) => c.archived === archived);
    } },
  { method: 'POST', pattern: /^\/conversations$/, handler: ({ body }) => {
      const title = (body as { title?: string })?.title ?? 'New Chat';
      const id = `conv-new-${CONVERSATIONS.length + 1}`;
      const now = '2026-05-14T10:00:00Z';
      return { conversation_id: id, title, created_at: now, updated_at: now,
        message_count: 0, document_ids: [], pinned: false, archived: false };
    } },
  { method: 'GET', pattern: /^\/conversations\/([^/]+)$/, handler: ({ params }) =>
      CONVERSATION_DETAIL[params[0]] ?? { conversation_id: params[0], title: 'Chat', document_ids: [], messages: [] } },
  { method: 'PATCH', pattern: /^\/conversations\/([^/]+)$/, handler: ({ params, body }) => {
      const c = CONVERSATIONS.find((x) => x.conversation_id === params[0]);
      return { ...c, ...(body as object) };
    } },
  { method: 'DELETE', pattern: /^\/conversations\/([^/]+)$/, handler: () => ({ ok: true }) },

  // ── Library (summary before :id) ─────────────────────────────────────────
  { method: 'GET', pattern: /^\/library\/summary$/, handler: () => LIBRARY_SUMMARY },
  { method: 'GET', pattern: /^\/library$/, handler: () => LIBRARY_DOCS },
  { method: 'GET', pattern: /^\/library\/([^/]+)$/, handler: ({ params }) =>
      LIBRARY_DOCS.find((d) => d.doc_id === params[0]) ?? LIBRARY_DOCS[0] },

  // ── Files ────────────────────────────────────────────────────────────────
  { method: 'GET', pattern: /^\/files$/, handler: () => FILES },
  { method: 'DELETE', pattern: /^\/files\/([^/]+)$/, handler: () => ({ ok: true }) },
  { method: 'POST', pattern: /^\/upload$/, handler: () =>
      ({ file_id: 'doc-upload-new', filename: 'uploaded_file.pdf', status: 'indexing' }) },

  // ── Document viewer content ──────────────────────────────────────────────
  { method: 'GET', pattern: /^\/docs\/([^/]+)\/content$/, handler: ({ params }) =>
      docContentFor(decodeURIComponent(params[0])) },

  // ── Knowledge collections ────────────────────────────────────────────────
  { method: 'GET', pattern: /^\/knowledge$/, handler: () => KNOWLEDGE },
  { method: 'POST', pattern: /^\/knowledge$/, handler: ({ body }) => {
      const b = body as { name?: string; description?: string };
      return { collection_id: `kc-new-${KNOWLEDGE.length + 1}`, name: b?.name ?? 'New Collection',
        description: b?.description ?? '', document_ids: [], document_count: 0,
        created_at: '2026-05-14T10:00:00Z', updated_at: '2026-05-14T10:00:00Z' };
    } },
  { method: 'GET', pattern: /^\/knowledge\/([^/]+)$/, handler: ({ params }) =>
      KNOWLEDGE_DETAIL[params[0]] ?? KNOWLEDGE_DETAIL['kc-eot'] },
  { method: 'PATCH', pattern: /^\/knowledge\/([^/]+)$/, handler: ({ params, body }) => {
      const c = KNOWLEDGE.find((x) => x.collection_id === params[0]);
      return { ...c, ...(body as object) };
    } },
  { method: 'DELETE', pattern: /^\/knowledge\/([^/]+)\/documents\/([^/]+)$/, handler: ({ params }) =>
      KNOWLEDGE.find((x) => x.collection_id === params[0]) },
  { method: 'POST', pattern: /^\/knowledge\/([^/]+)\/documents$/, handler: ({ params }) =>
      KNOWLEDGE.find((x) => x.collection_id === params[0]) },
  { method: 'DELETE', pattern: /^\/knowledge\/([^/]+)$/, handler: () => ({ ok: true }) },

  // ── Usage / stats / indexing ─────────────────────────────────────────────
  { method: 'GET', pattern: /^\/usage$/, handler: () => USAGE },
  { method: 'GET', pattern: /^\/stats$/, handler: () => STATS },
  { method: 'GET', pattern: /^\/indexing\/status$/, handler: () => INDEXING_STATUS },

  // ── Chat ─────────────────────────────────────────────────────────────────
  { method: 'POST', pattern: /^\/chat$/, handler: ({ body }) => chatAnswerFor(body) },

  // ── Admin: data tables ───────────────────────────────────────────────────
  { method: 'GET', pattern: /^\/admin\/data-tables\/status$/, handler: () => COST_TABLE_PLACEHOLDER },
  { method: 'POST', pattern: /^\/admin\/data-tables\/reindex$/, handler: () =>
      ({ dry_run: false, scheduled: 2, files: ['doc-xls-0044', 'doc-xls-0045'] }) },
  { method: 'POST', pattern: /^\/admin\/data-tables\/diagnose$/, handler: () =>
      ({ ok: true, file: { id: 'doc-xls-0044', name: 'Cost_Tracker_Q2_2026.xlsx', extension: 'xlsx', data_table_status: 'registered' } }) },
];

export { ok };
