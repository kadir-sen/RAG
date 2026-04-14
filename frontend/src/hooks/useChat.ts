import { useMutation, useQueryClient } from '@tanstack/react-query';
import { sendMessage } from '../api/chatApi';
import { useChatStore } from '../stores/chatStore';
import type { Message } from '../types/chat';

const genId = () => `${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;

function friendlyError(error: Error): string {
  const msg = error.message.toLowerCase();
  if (msg.includes('network error') || msg.includes('err_connection'))
    return 'Unable to reach the server. Please check your connection.';
  if (msg.includes('timeout'))
    return 'The request took too long. Please try a simpler query.';
  if (msg.includes('500') || msg.includes('internal server'))
    return 'Something went wrong on our end. Please try again.';
  return 'An unexpected error occurred. Please try again.';
}

export function useChat() {
  const { messages, isLoading, addMessage, setLoading } = useChatStore();
  const queryClient = useQueryClient();

  const send = useMutation({
    mutationFn: async (text: string) => {
      const userMsg: Message = {
        id: `u_${genId()}`,
        role: 'user',
        content: text,
        timestamp: Date.now(),
      };
      addMessage(userMsg);
      setLoading(true);

      // Read live store values to avoid stale closure
      const { activeConversationId: currentConvId, activeMode: currentMode,
        selectedEmailIds: currentEmailIds } = useChatStore.getState();

      const docIds = currentMode === 'correspondence' && currentEmailIds.length > 0
        ? currentEmailIds
        : undefined;
      const emailIds = currentMode === 'correspondence' && currentEmailIds.length > 0
        ? currentEmailIds
        : undefined;

      const response = await sendMessage(text, currentConvId, docIds, emailIds, currentMode);
      return response;
    },
    onSuccess: (response) => {
      const assistantMsg: Message = {
        id: `a_${genId()}`,
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
        id: `e_${genId()}`,
        role: 'assistant',
        content: friendlyError(error),
        timestamp: Date.now(),
      };
      addMessage(errorMsg);
      setLoading(false);
    },
  });

  return { messages, isLoading, sendMessage: send.mutate };
}
