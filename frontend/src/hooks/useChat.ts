import { useMutation, useQueryClient } from '@tanstack/react-query';
import { sendMessage } from '../api/chatApi';
import { useChatStore } from '../stores/chatStore';
import type { Message } from '../types/chat';

let msgCounter = 0;

export function useChat() {
  const { messages, activeConversationId, isLoading, addMessage, setLoading,
    activeMode, selectedEmailIds } = useChatStore();
  const queryClient = useQueryClient();

  const send = useMutation({
    mutationFn: async (text: string) => {
      const userMsg: Message = {
        id: `u_${++msgCounter}`,
        role: 'user',
        content: text,
        timestamp: Date.now(),
      };
      addMessage(userMsg);
      setLoading(true);

      // In correspondence mode, scope to selected emails and pass email_ids
      const docIds = activeMode === 'correspondence' && selectedEmailIds.length > 0
        ? selectedEmailIds
        : undefined;
      const emailIds = activeMode === 'correspondence' && selectedEmailIds.length > 0
        ? selectedEmailIds
        : undefined;

      const response = await sendMessage(text, activeConversationId, docIds, emailIds);
      return response;
    },
    onSuccess: (response) => {
      const assistantMsg: Message = {
        id: `a_${++msgCounter}`,
        role: 'assistant',
        content: response.assistant_text,
        timestamp: Date.now(),
        response,
      };
      addMessage(assistantMsg);
      setLoading(false);
      queryClient.invalidateQueries({ queryKey: ['conversations'] });
    },
    onError: (error: Error) => {
      const errorMsg: Message = {
        id: `e_${++msgCounter}`,
        role: 'assistant',
        content: `Error: ${error.message}`,
        timestamp: Date.now(),
      };
      addMessage(errorMsg);
      setLoading(false);
    },
  });

  return { messages, isLoading, sendMessage: send.mutate };
}
