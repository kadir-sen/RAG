import { useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { sendMessage } from '../api/chatApi';
import { useChatStore } from '../stores/chatStore';
import { useAuthStore } from '../stores/authStore';
import type { Message } from '../types/chat';
import type { QueryProgress } from '../types/api';

const genId = () => `${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;

interface ErrorWithResponse extends Error {
  response?: {
    status?: number;
    data?: {
      error?: string;
      detail?: string;
    };
  };
}

function friendlyError(error: Error): string {
  const e = error as ErrorWithResponse;
  if (e.response?.status === 402) {
    if (e.response.data?.error === 'credit_balance_exhausted') {
      return 'Your credit balance is fully consumed. Contact your administrator to top it up.';
    }
    if (e.response.data?.error === 'token_quota_exceeded') {
      return 'Your token quota is fully consumed. Contact your administrator to top it up.';
    }
    return 'The system budget has been reached. Try again later.';
  }
  if (e.response?.status === 403) {
    const detail = e.response.data?.detail ?? '';
    if (detail.startsWith('feature_not_available')) {
      return 'This mode is not available on your account. Ask your administrator to enable it.';
    }
  }
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
  const inFlightRef = useRef(false);
  const lastFailedTextRef = useRef<string | null>(null);
  // request_id of the in-flight query, so the activity feed can poll its progress.
  const [activeRequestId, setActiveRequestId] = useState<string | null>(null);
  const requestIdRef = useRef<string | null>(null);

  const send = useMutation({
    mutationFn: async (text: string) => {
      if (inFlightRef.current) throw new Error('DUPLICATE');
      inFlightRef.current = true;
      lastFailedTextRef.current = text;

      const userMsg: Message = {
        id: `u_${genId()}`,
        role: 'user',
        content: text,
        timestamp: Date.now(),
      };
      addMessage(userMsg);
      setLoading(true);

      // Correlate the live activity feed: generate a request_id, expose it so
      // useActivityFeed can poll /chat/progress/{id} while this POST is in flight.
      const requestId = `req_${genId()}`;
      requestIdRef.current = requestId;
      setActiveRequestId(requestId);

      // Read live store values to avoid stale closure
      const { activeConversationId: currentConvId, selectedIds } = useChatStore.getState();

      // Selection is mode-less now: send the picked files as BOTH doc_ids and
      // email_ids. The backend sorts them by type — _build_email_context keeps
      // emails, _build_document_context keeps non-email docs — so each lands in
      // the right context block regardless of which sidebar folder it came from.
      const selected = selectedIds.length > 0 ? selectedIds : undefined;

      const response = await sendMessage(text, currentConvId, selected, selected, null, requestId);
      return response;
    },
    onSuccess: (response) => {
      inFlightRef.current = false;
      lastFailedTextRef.current = null;
      // Capture the final activity steps (last polled snapshot) so the finished
      // message keeps a collapsible "Steps" trail.
      const rid = requestIdRef.current;
      const progress = rid
        ? queryClient.getQueryData<QueryProgress>(['chatProgress', rid])
        : undefined;
      const assistantMsg: Message = {
        id: `a_${genId()}`,
        role: 'assistant',
        content: response.assistant_text,
        timestamp: Date.now(),
        response,
        activities: progress?.steps,
      };
      addMessage(assistantMsg);
      setLoading(false);
      setActiveRequestId(null);
      requestIdRef.current = null;
      if (response.quota) {
        useAuthStore.getState().updateQuota(response.quota);
      }
      queryClient.invalidateQueries({ queryKey: ['conversations'] });
    },
    onError: (error: Error) => {
      inFlightRef.current = false;
      setActiveRequestId(null);
      requestIdRef.current = null;
      if (error.message === 'DUPLICATE') return;
      const e = error as ErrorWithResponse;
      // 402 / quota exhausted — zero out the user's bar so the UI matches the
      // backend's "no more requests" state without waiting for a /me poll.
      if (e.response?.status === 402 && ['token_quota_exceeded', 'credit_balance_exhausted'].includes(e.response.data?.error ?? '')) {
        void useAuthStore.getState().refreshMe();
      }
      const errorMsg: Message = {
        id: `e_${genId()}`,
        role: 'assistant',
        content: friendlyError(error),
        timestamp: Date.now(),
        failedText: lastFailedTextRef.current ?? undefined,
      };
      addMessage(errorMsg);
      setLoading(false);
    },
  });

  return { messages, isLoading, isPending: send.isPending, sendMessage: send.mutate, activeRequestId };
}
