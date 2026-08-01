import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getConversationDocs,
  addDocsToConversation,
  removeDocFromConversation,
} from '../api/libraryApi';
import { useProjectStore } from '../stores/projectStore';

export function useConversationDocs(conversationId: string | null) {
  const queryClient = useQueryClient();
  const projectId = useProjectStore((state) => state.selectedProjectId);

  const queryKey = ['conversation-docs', projectId, conversationId];

  const { data: docs = [], isLoading } = useQuery({
    queryKey,
    queryFn: () => getConversationDocs(conversationId!),
    enabled: Boolean(projectId && conversationId),
    staleTime: 30_000,
  });

  const addDocs = useMutation({
    mutationFn: (docIds: string[]) => addDocsToConversation(conversationId!, docIds),
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
  });

  const removeDoc = useMutation({
    mutationFn: (docId: string) => removeDocFromConversation(conversationId!, docId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
  });

  return { docs, isLoading, addDocs, removeDoc };
}
