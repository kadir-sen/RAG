import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Message } from '../types/chat';

export type AppMode = 'chat' | 'correspondence' | 'document_analysis' | null;

interface ChatState {
  messages: Message[];
  activeConversationId: string;
  isLoading: boolean;
  documentIds: string[];
  activeMode: AppMode;
  selectedEmailIds: string[];
  setConversation: (id: string, messages?: Message[], documentIds?: string[]) => void;
  addMessage: (msg: Message) => void;
  setLoading: (v: boolean) => void;
  setDocumentIds: (ids: string[]) => void;
  clearMessages: () => void;
  setMode: (mode: AppMode) => void;
  setSelectedEmails: (ids: string[]) => void;
  toggleEmailSelection: (id: string) => void;
}

export const useChatStore = create<ChatState>()(
  persist(
    (set) => ({
      messages: [],
      activeConversationId: '',
      isLoading: false,
      documentIds: [],
      activeMode: null,
      selectedEmailIds: [],

      setConversation: (id, messages = [], documentIds = []) =>
        set({
          activeConversationId: id,
          messages,
          documentIds,
          // An ID means the user explicitly opened a conversation — switch to
          // the chat surface even if the loaded messages array is empty (the
          // backend file could be temporarily empty, the fetch could still be
          // mid-flight, etc.). Falling back to `null` here would render the
          // WelcomeScreen and make it look like the conversation never loaded.
          activeMode: id ? 'chat' : null,
          selectedEmailIds: [],
        }),

      addMessage: (msg) =>
        set((s) => ({ messages: [...s.messages, msg] })),

      setLoading: (v) => set({ isLoading: v }),

      setDocumentIds: (ids) => set({ documentIds: ids }),

      clearMessages: () => set({ messages: [], documentIds: [] }),

      setMode: (mode) => set({ activeMode: mode }),

      setSelectedEmails: (ids) => set({ selectedEmailIds: ids }),

      toggleEmailSelection: (id) =>
        set((s) => ({
          selectedEmailIds: s.selectedEmailIds.includes(id)
            ? s.selectedEmailIds.filter((eid) => eid !== id)
            : [...s.selectedEmailIds, id],
        })),
    }),
    {
      name: 'constructioniq-chat',
      // Only persist conversation ID — messages are loaded from backend on demand
      partialize: (state) => ({
        activeConversationId: state.activeConversationId,
      }),
    },
  ),
);
