import { useEffect, useCallback, useRef } from 'react';
import { useChat } from '../hooks/useChat';
import { useConversations } from '../hooks/useConversations';
import { useUIStore } from '../stores/uiStore';
import { useChatStore, type AppMode } from '../stores/chatStore';
import { getConversation } from '../api/conversationApi';
import ConversationSidebar from '../components/sidebar/ConversationSidebar';
import ChatStream from '../components/chat/ChatStream';
import ChatInput from '../components/chat/ChatInput';
import WelcomeScreen from '../components/chat/WelcomeScreen';
import RightDocViewer from '../components/viewer/RightDocViewer';

export default function ChatPage() {
  const { messages, isLoading, sendMessage } = useChat();
  const { conversations, createConversation } = useConversations();
  const { rightPanelOpen, openDocument } = useUIStore();
  const { activeConversationId, setConversation, activeMode, setMode } = useChatStore();
  const pendingMessageRef = useRef<string | null>(null);
  const restoredRef = useRef(false);

  // Restore persisted conversation on page load
  useEffect(() => {
    if (restoredRef.current) return;
    if (activeConversationId && messages.length === 0 && !isLoading) {
      restoredRef.current = true;
      getConversation(activeConversationId)
        .then((conv) => {
          if (conv?.messages?.length) {
            const restored = conv.messages.map((m: { role: string; content: string; timestamp: string; response?: unknown }, i: number) => ({
              id: `r_${i}_${Date.now()}`,
              role: m.role as 'user' | 'assistant',
              content: m.content,
              timestamp: new Date(m.timestamp).getTime(),
              response: m.response ?? undefined,
            }));
            setConversation(activeConversationId, restored, conv.document_ids ?? []);
          }
        })
        .catch(() => {
          // Conversation may have been deleted — reset
          setConversation('');
        });
    } else {
      restoredRef.current = true;
    }
  }, [activeConversationId, messages.length, isLoading, setConversation]);

  useEffect(() => {
    if (!activeConversationId && conversations.length > 0) {
      setConversation(conversations[0].conversation_id);
    }
  }, [activeConversationId, conversations, setConversation]);

  useEffect(() => {
    if (activeConversationId && pendingMessageRef.current) {
      const text = pendingMessageRef.current;
      pendingMessageRef.current = null;
      sendMessage(text);
    }
  }, [activeConversationId, sendMessage]);

  const handleSend = useCallback(
    (text: string) => {
      if (!activeConversationId) {
        pendingMessageRef.current = text;
        createConversation('New Chat');
        return;
      }
      sendMessage(text);
    },
    [activeConversationId, createConversation, sendMessage],
  );

  const handleModeSelect = useCallback((mode: AppMode) => setMode(mode), [setMode]);
  const handleBack = useCallback(() => setMode(null), [setMode]);

  const showWelcome = activeMode === null && messages.length === 0 && !isLoading;
  const modeLabel = activeMode === 'correspondence'
    ? 'Correspondence Mode'
    : activeMode === 'document_analysis'
      ? 'Document Analysis'
      : '';

  return (
    <div className="flex h-full w-full overflow-hidden">
      {/* Sidebar */}
      <ConversationSidebar onSend={handleSend} />

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0 h-full">
        {/* Mode header — only for correspondence/document_analysis */}
        {activeMode && activeMode !== 'chat' && (
          <div className="flex items-center gap-3 px-6 py-3 border-b border-[var(--border)] shrink-0">
            <button
              onClick={handleBack}
              className="text-xs text-[var(--text-secondary)] hover:text-white transition-colors flex items-center gap-1"
            >
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <path d="M8 2L4 6l4 4" />
              </svg>
              Back
            </button>
            <span className="text-sm font-medium text-[var(--accent)]">{modeLabel}</span>
          </div>
        )}

        {/* Content area */}
        {showWelcome ? (
          <WelcomeScreen onModeSelect={handleModeSelect} onSend={handleSend} />
        ) : (
          <div className="flex-1 flex flex-col min-h-0 relative">
            <ChatStream
              messages={messages}
              isLoading={isLoading}
              onDocClick={openDocument}
            />
            <ChatInput onSend={handleSend} disabled={isLoading} />
          </div>
        )}
      </div>

      {/* Right viewer */}
      {rightPanelOpen && (
        <div className="w-[420px] flex-shrink-0 h-full">
          <RightDocViewer />
        </div>
      )}
    </div>
  );
}
