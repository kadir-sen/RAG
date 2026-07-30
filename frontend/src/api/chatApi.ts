import apiClient from './client';
import type { ChatResponse, QueryProgress } from '../types/api';
import { downloadPost } from './download';

export async function sendMessage(
  message: string,
  conversationId: string,
  docIds?: string[],
  emailIds?: string[],
  mode?: string | null,
  requestId?: string,
): Promise<ChatResponse> {
  const payload: Record<string, unknown> = {
    message,
    conversation_id: conversationId,
  };
  if (docIds && docIds.length > 0) {
    payload.doc_ids = docIds;
  }
  if (emailIds && emailIds.length > 0) {
    payload.email_ids = emailIds;
  }
  if (mode) {
    payload.mode = mode;
  }
  if (requestId) {
    payload.request_id = requestId;
  }
  // RAG-synthesis queries routinely take 2-6 minutes on the 2 GB demo box
  // (swap-bound), well past the 120s client default that covers every other
  // request. Without this override the backend finishes but the UI shows
  // "The request took too long" — override the timeout for /chat only.
  const { data } = await apiClient.post<ChatResponse>('/chat', payload, {
    timeout: 360_000,
  });
  return data;
}

// Poll the live activity feed for an in-flight query (same request_id sent above).
export async function getQueryProgress(requestId: string): Promise<QueryProgress> {
  const { data } = await apiClient.get<QueryProgress>(`/chat/progress/${requestId}`);
  return data;
}

/**
 * Download one answer as a Word document.
 *
 * The answer is posted rather than referenced by id: the server keeps only the
 * first 20 preview rows and no row total, so it could not render a better
 * document than the one on screen — and this way the download behaves the same
 * for a fresh answer and a reopened conversation, including the ones already on
 * disk.
 *
 * `totalRows` is passed only when it is actually known. A restored answer has no
 * memory of the query's total, and the document says so rather than inventing
 * one.
 */
export async function downloadAnswerDocx(args: {
  question: string;
  answer: string;
  citations?: { doc_name: string; anchor?: string; snippet?: string }[];
  sql?: string;
  tableColumns?: string[];
  tableRows?: unknown[][];
  totalRows?: number | null;
}): Promise<void> {
  await downloadPost(
    '/chat/document',
    {
      question: args.question,
      answer: args.answer,
      citations: (args.citations ?? []).map((c) => ({
        doc_name: c.doc_name,
        anchor: c.anchor ?? '',
        snippet: c.snippet ?? '',
      })),
      sql: args.sql ?? '',
      table_columns: args.tableColumns ?? [],
      table_rows: args.tableRows ?? [],
      total_rows: args.totalRows ?? null,
    },
    'COAir-answer.docx',
  );
}
