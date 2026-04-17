import apiClient from './client';
import type { ConversationMeta } from '../types/api';

export async function listConversations(
  archived = false,
): Promise<ConversationMeta[]> {
  const { data } = await apiClient.get<ConversationMeta[]>('/conversations', {
    params: archived ? { archived: true } : undefined,
  });
  return data;
}

export async function createConversation(
  title = 'New Chat',
): Promise<ConversationMeta> {
  const { data } = await apiClient.post<ConversationMeta>('/conversations', {
    title,
  });
  return data;
}

export async function getConversation(id: string) {
  const { data } = await apiClient.get(`/conversations/${id}`);
  return data;
}

export async function deleteConversation(id: string) {
  await apiClient.delete(`/conversations/${id}`);
}

export async function renameConversation(id: string, title: string) {
  await apiClient.patch(`/conversations/${id}`, { title });
}

export async function pinConversation(
  id: string,
  pinned: boolean,
): Promise<ConversationMeta> {
  const { data } = await apiClient.patch<ConversationMeta>(
    `/conversations/${id}/pin`,
    { pinned },
  );
  return data;
}

export async function archiveConversation(
  id: string,
  archived: boolean,
): Promise<ConversationMeta> {
  const { data } = await apiClient.patch<ConversationMeta>(
    `/conversations/${id}/archive`,
    { archived },
  );
  return data;
}
