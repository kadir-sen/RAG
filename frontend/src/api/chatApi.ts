import apiClient from './client';
import type { ChatResponse } from '../types/api';

export async function sendMessage(
  message: string,
  conversationId: string,
  docIds?: string[],
  emailIds?: string[],
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
  const { data } = await apiClient.post<ChatResponse>('/chat', payload);
  return data;
}
