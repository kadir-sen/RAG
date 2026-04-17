import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  listCollections,
  createCollection,
  getCollection,
  updateCollection,
  deleteCollection,
  addDocumentsToCollection,
  removeDocumentFromCollection,
} from '../api/knowledgeApi';

export function useKnowledgeCollections() {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ['knowledge'],
    queryFn: listCollections,
    staleTime: 30_000,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['knowledge'] });
  };

  const create = useMutation({
    mutationFn: ({ name, description }: { name: string; description?: string }) =>
      createCollection(name, description),
    onSuccess: invalidate,
  });

  const update = useMutation({
    mutationFn: ({
      id,
      name,
      description,
    }: {
      id: string;
      name?: string;
      description?: string;
    }) => updateCollection(id, { name, description }),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: deleteCollection,
    onSuccess: invalidate,
  });

  const addDocs = useMutation({
    mutationFn: ({ id, docIds }: { id: string; docIds: string[] }) =>
      addDocumentsToCollection(id, docIds),
    onSuccess: (_, vars) => {
      invalidate();
      queryClient.invalidateQueries({ queryKey: ['knowledge', vars.id] });
    },
  });

  const removeDoc = useMutation({
    mutationFn: ({ id, docId }: { id: string; docId: string }) =>
      removeDocumentFromCollection(id, docId),
    onSuccess: (_, vars) => {
      invalidate();
      queryClient.invalidateQueries({ queryKey: ['knowledge', vars.id] });
    },
  });

  return {
    collections: query.data ?? [],
    isLoading: query.isLoading,
    createCollection: create.mutateAsync,
    updateCollection: update.mutateAsync,
    deleteCollection: remove.mutate,
    addDocuments: addDocs.mutateAsync,
    removeDocument: removeDoc.mutate,
  };
}

export function useKnowledgeCollection(id: string | null) {
  return useQuery({
    queryKey: ['knowledge', id],
    queryFn: () => getCollection(id as string),
    enabled: !!id,
    staleTime: 30_000,
  });
}
