import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  listConversations,
  createConversation,
  deleteConversation,
  renameConversation,
  pinConversation,
  archiveConversation,
} from '../api/conversationApi';
import { useChatStore } from '../stores/chatStore';

export function useConversations(options?: { archived?: boolean }) {
  const archived = options?.archived ?? false;
  const queryClient = useQueryClient();
  const setConversation = useChatStore((s) => s.setConversation);

  const query = useQuery({
    queryKey: ['conversations', { archived }],
    queryFn: () => listConversations(archived),
    staleTime: 30_000,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['conversations'] });
  };

  const create = useMutation({
    mutationFn: createConversation,
    onSuccess: (conv) => {
      setConversation(conv.conversation_id, []);
      invalidate();
    },
  });

  const remove = useMutation({
    mutationFn: deleteConversation,
    onSuccess: invalidate,
  });

  const rename = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      renameConversation(id, title),
    onSuccess: invalidate,
  });

  const pin = useMutation({
    mutationFn: ({ id, pinned }: { id: string; pinned: boolean }) =>
      pinConversation(id, pinned),
    onSuccess: invalidate,
  });

  const archive = useMutation({
    mutationFn: ({ id, archived }: { id: string; archived: boolean }) =>
      archiveConversation(id, archived),
    onSuccess: invalidate,
  });

  return {
    conversations: query.data ?? [],
    isLoading: query.isLoading,
    createConversation: create.mutateAsync,
    deleteConversation: remove.mutate,
    renameConversation: rename.mutate,
    pinConversation: pin.mutate,
    archiveConversation: archive.mutate,
  };
}
