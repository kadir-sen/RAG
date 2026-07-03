import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Message } from '../types/chat';

interface ChatState {
  messages: Message[];
  activeConversationId: string;
  isLoading: boolean;
  documentIds: string[];
  // Unified selection: documents AND emails picked from the sidebar (by doc_id).
  // Sent with every message as context; rendered as tiles above the chat input.
  selectedIds: string[];
  setConversation: (id: string, messages?: Message[], documentIds?: string[]) => void;
  addMessage: (msg: Message) => void;
  setLoading: (v: boolean) => void;
  setDocumentIds: (ids: string[]) => void;
  clearMessages: () => void;
  setSelectedIds: (ids: string[]) => void;
  toggleSelection: (id: string) => void;
  clearSelection: () => void;
}

export const useChatStore = create<ChatState>()(
  persist(
    (set) => ({
      messages: [],
      activeConversationId: '',
      isLoading: false,
      documentIds: [],
      selectedIds: [],

      setConversation: (id, messages = [], documentIds = []) =>
        set({
          activeConversationId: id,
          messages,
          documentIds,
          selectedIds: [],
        }),

      addMessage: (msg) =>
        set((s) => ({ messages: [...s.messages, msg] })),

      setLoading: (v) => set({ isLoading: v }),

      setDocumentIds: (ids) => set({ documentIds: ids }),

      clearMessages: () => set({ messages: [], documentIds: [] }),

      setSelectedIds: (ids) => set({ selectedIds: ids }),

      toggleSelection: (id) =>
        set((s) => ({
          selectedIds: s.selectedIds.includes(id)
            ? s.selectedIds.filter((x) => x !== id)
            : [...s.selectedIds, id],
        })),

      clearSelection: () => set({ selectedIds: [] }),
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
