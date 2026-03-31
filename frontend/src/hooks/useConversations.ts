import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  listConversations,
  createConversation,
  deleteConversation,
  renameConversation,
} from '../api/conversationApi';
import { useChatStore } from '../stores/chatStore';

export function useConversations() {
  const queryClient = useQueryClient();
  const setConversation = useChatStore((s) => s.setConversation);

  const query = useQuery({
    queryKey: ['conversations'],
    queryFn: listConversations,
    staleTime: 30_000,
  });

  const create = useMutation({
    mutationFn: createConversation,
    onSuccess: (conv) => {
      setConversation(conv.conversation_id, []);
      queryClient.invalidateQueries({ queryKey: ['conversations'] });
    },
  });

  const remove = useMutation({
    mutationFn: deleteConversation,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['conversations'] });
    },
  });

  const rename = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      renameConversation(id, title),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['conversations'] });
    },
  });

  return {
    conversations: query.data ?? [],
    isLoading: query.isLoading,
    createConversation: create.mutate,
    deleteConversation: remove.mutate,
    renameConversation: rename.mutate,
  };
}
