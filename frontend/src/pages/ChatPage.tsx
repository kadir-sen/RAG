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
import DocumentAnalysisIntro from '../components/chat/DocumentAnalysisIntro';
import CorrespondenceCenter from '../components/chat/CorrespondenceCenter';
import RightDocViewer from '../components/viewer/RightDocViewer';
import MonoTag from '../components/ui/MonoTag';

export default function ChatPage() {
  const { messages, isLoading, isPending, sendMessage } = useChat();
  const { conversations, createConversation } = useConversations();
  const { rightPanelOpen, openDocument } = useUIStore();
  const { activeConversationId, setConversation, activeMode, setMode, selectedEmailIds } = useChatStore();
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
    async (text: string) => {
      if (!activeConversationId) {
        pendingMessageRef.current = text;
        try {
          await createConversation('New Chat');
        } catch {
          const lostText = pendingMessageRef.current;
          pendingMessageRef.current = null;
          if (lostText) {
            useChatStore.getState().addMessage({
              id: `e_${Date.now()}`,
              role: 'assistant',
              content: 'Could not create a conversation. Please try again.',
              timestamp: Date.now(),
            });
          }
        }
        return;
      }
      sendMessage(text);
    },
    [activeConversationId, createConversation, sendMessage],
  );

  const handleModeSelect = useCallback((mode: AppMode) => setMode(mode), [setMode]);
  const handleBack = useCallback(() => setMode(null), [setMode]);

  // Only show the WelcomeScreen when the app is on a truly clean slate:
  // no active conversation AND no mode picked. If a conversation ID is set
  // (the user clicked a row in the sidebar), keep the chat surface visible
  // even if the backend hasn't returned messages yet — otherwise an empty
  // load looks identical to "new chat".
  const showWelcome =
    activeMode === null &&
    !activeConversationId &&
    messages.length === 0 &&
    !isLoading;
  const showDocAnalysisIntro =
    activeMode === 'document_analysis' && messages.length === 0 && !isLoading;
  const showCorrespondenceCenter =
    activeMode === 'correspondence' && messages.length === 0 && !isLoading;
  const modeMeta = activeMode === 'correspondence'
    ? { label: 'CORRESPONDENCE MODE', sublabel: 'thread digest · email trace' }
    : activeMode === 'document_analysis'
      ? { label: 'DOCUMENT ANALYSIS', sublabel: 'topic → chronological roadmap' }
      : null;

  return (
    <div className="flex h-full w-full overflow-clip">
      {/* Sidebar */}
      <ConversationSidebar onSend={handleSend} />

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0 h-full">
        {/* Mode header — only for correspondence/document_analysis */}
        {activeMode && activeMode !== 'chat' && modeMeta && (
          <div className="flex items-center gap-3 px-6 py-2.5 border-b border-[var(--border)] shrink-0 bg-[var(--bg-secondary)]/40">
            <button
              onClick={handleBack}
              aria-label="Back to mode selection"
              className="font-mono text-[11px] text-[var(--text-secondary)] hover:text-white transition-colors flex items-center gap-1"
            >
              <svg aria-hidden="true" width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <path d="M8 2L4 6l4 4" />
              </svg>
              Back
            </button>
            <MonoTag tone="accent">{modeMeta.label}</MonoTag>
            <span className="font-mono text-[11px] text-[var(--text-secondary)] tracking-wide">
              {modeMeta.sublabel}
            </span>
            <span className="flex-1" />
            {activeMode === 'correspondence' && selectedEmailIds.length > 0 && (
              <MonoTag tone="accent">{selectedEmailIds.length} emails scoped</MonoTag>
            )}
          </div>
        )}

        {/* Content area */}
        <div className="flex-1 flex flex-col min-h-0 relative">
          {showWelcome ? (
            <WelcomeScreen onModeSelect={handleModeSelect} />
          ) : showCorrespondenceCenter ? (
            <CorrespondenceCenter onSend={handleSend} />
          ) : showDocAnalysisIntro ? (
            <DocumentAnalysisIntro onSend={handleSend} />
          ) : (
            <ChatStream
              messages={messages}
              isLoading={isLoading}
              onDocClick={openDocument}
              onRetry={sendMessage}
            />
          )}
          <ChatInput onSend={handleSend} disabled={isLoading || isPending} />
        </div>
      </div>

      {/* Right viewer */}
      {rightPanelOpen && (
        <div className="w-[340px] lg:w-[420px] flex-shrink-0 h-full">
          <RightDocViewer />
        </div>
      )}
    </div>
  );
}
