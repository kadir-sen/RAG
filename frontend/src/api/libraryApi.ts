import api from './client';
import type { LibraryDocument } from '../types/api';

export async function getLibrary(): Promise<LibraryDocument[]> {
  const { data } = await api.get<LibraryDocument[]>('/library');
  return data;
}

export async function getLibraryDoc(docId: string): Promise<LibraryDocument> {
  const { data } = await api.get<LibraryDocument>(`/library/${docId}`);
  return data;
}

export async function getConversationDocs(convId: string): Promise<LibraryDocument[]> {
  const { data } = await api.get<LibraryDocument[]>(`/conversations/${convId}/documents`);
  return data;
}

export async function addDocsToConversation(
  convId: string,
  docIds: string[],
): Promise<{ ok: boolean; document_ids: string[] }> {
  const { data } = await api.post(`/conversations/${convId}/documents`, { doc_ids: docIds });
  return data;
}

export async function removeDocFromConversation(
  convId: string,
  docId: string,
): Promise<{ ok: boolean }> {
  const { data } = await api.delete(`/conversations/${convId}/documents/${docId}`);
  return data;
}
