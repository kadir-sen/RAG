import apiClient from './client';
import type { ChatResponse, QueryProgress } from '../types/api';

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
  const { data } = await apiClient.post<ChatResponse>('/chat', payload);
  return data;
}

// Poll the live activity feed for an in-flight query (same request_id sent above).
export async function getQueryProgress(requestId: string): Promise<QueryProgress> {
  const { data } = await apiClient.get<QueryProgress>(`/chat/progress/${requestId}`);
  return data;
}
