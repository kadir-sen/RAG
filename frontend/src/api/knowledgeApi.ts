import apiClient from './client';
import type {
  KnowledgeCollection,
  KnowledgeCollectionDetail,
} from '../types/api';

export async function listCollections(): Promise<KnowledgeCollection[]> {
  const { data } = await apiClient.get<KnowledgeCollection[]>('/knowledge');
  return data;
}

export async function createCollection(
  name: string,
  description = '',
): Promise<KnowledgeCollection> {
  const { data } = await apiClient.post<KnowledgeCollection>('/knowledge', {
    name,
    description,
  });
  return data;
}

export async function getCollection(id: string): Promise<KnowledgeCollectionDetail> {
  const { data } = await apiClient.get<KnowledgeCollectionDetail>(
    `/knowledge/${id}`,
  );
  return data;
}

export async function updateCollection(
  id: string,
  payload: { name?: string; description?: string },
): Promise<KnowledgeCollection> {
  const { data } = await apiClient.patch<KnowledgeCollection>(
    `/knowledge/${id}`,
    payload,
  );
  return data;
}

export async function deleteCollection(id: string): Promise<void> {
  await apiClient.delete(`/knowledge/${id}`);
}

export async function addDocumentsToCollection(
  id: string,
  docIds: string[],
): Promise<KnowledgeCollection> {
  const { data } = await apiClient.post<KnowledgeCollection>(
    `/knowledge/${id}/documents`,
    { doc_ids: docIds },
  );
  return data;
}

export async function removeDocumentFromCollection(
  id: string,
  docId: string,
): Promise<KnowledgeCollection> {
  const { data } = await apiClient.delete<KnowledgeCollection>(
    `/knowledge/${id}/documents/${docId}`,
  );
  return data;
}
