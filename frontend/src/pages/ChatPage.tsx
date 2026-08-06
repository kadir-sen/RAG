import { useEffect, useCallback, useRef, useState } from 'react';
import { useChat } from '../hooks/useChat';
import { useConversations } from '../hooks/useConversations';
import { useUIStore } from '../stores/uiStore';
import { useChatStore } from '../stores/chatStore';
import { getConversation } from '../api/conversationApi';
import ConversationSidebar from '../components/sidebar/ConversationSidebar';
import ChatStream from '../components/chat/ChatStream';
import ChatInput from '../components/chat/ChatInput';
import WelcomeScreen from '../components/chat/WelcomeScreen';
import SelectedContextBar from '../components/chat/SelectedContextBar';

export default function ChatPage() {
  const { messages, isLoading, isPending, sendMessage, activeRequestId } = useChat();
  const { createConversation } = useConversations();
  const { openDocument } = useUIStore();
  const { activeConversationId, setConversation } = useChatStore();
  const pendingMessageRef = useRef<string | null>(null);
  const restoredRef = useRef(false);
  // True between page load and the first restore-from-storage finishing.
  // While this is true we render a neutral placeholder instead of the empty
  // ChatStream — that mid-load flash is what makes a fresh tab look like
  // "the chat is already half-filled" before the API responds.
  const [isRestoring, setIsRestoring] = useState(
    () => Boolean(activeConversationId) && messages.length === 0,
  );

  useEffect(() => {
    if (restoredRef.current) return;
    if (activeConversationId && messages.length === 0 && !isLoading) {
      restoredRef.current = true;
      setIsRestoring(true);
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
          } else {
            // The persisted id refers to an empty/missing record. Drop it
            // so the next paint shows the WelcomeScreen, not a blank stream.
            setConversation('');
          }
        })
        .catch(() => {
          // Conversation may have been deleted — reset
          setConversation('');
        })
        .finally(() => setIsRestoring(false));
    } else {
      restoredRef.current = true;
      setIsRestoring(false);
    }
  }, [activeConversationId, messages.length, isLoading, setConversation]);

  // No auto-select on first load. Dropping a brand-new visitor (or a fresh
  // tab in a different user agent) straight into the most recent stored
  // conversation surfaced someone else's chat content for a heartbeat, and
  // skipped the WelcomeScreen / mode picker entirely. The user explicitly
  // clicks a row in the sidebar when they want to open a previous chat.

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

  // Single home surface. Show the home empty-state whenever there's no open
  // conversation and no messages yet. There are no modes anymore — the user
  // types anything, the backend router decides the skill, and the rich
  // chronological table renders inline. File selection lives in the sidebar.
  const showWelcome =
    !activeConversationId && messages.length === 0 && !isLoading;

  return (
    <div className="flex h-full w-full overflow-clip">
      {/* Sidebar */}
      <ConversationSidebar onSend={handleSend} />

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0 h-full">
        {/* Content area */}
        <div className="flex-1 flex flex-col min-h-0 relative">
          {isRestoring ? (
            <div
              className="flex-1 flex items-center justify-center text-[var(--text-muted)] font-mono text-[11px] tracking-wider"
              aria-live="polite"
            >
              loading conversation…
            </div>
          ) : showWelcome ? (
            <WelcomeScreen onSend={handleSend} />
          ) : (
            <ChatStream
              messages={messages}
              isLoading={isLoading}
              onDocClick={openDocument}
              onRetry={sendMessage}
              activeRequestId={activeRequestId}
            />
          )}
          {/* Selected-files tiles + composer at the bottom of every surface. */}
          {!isRestoring && (
            <>
              <div className="px-4 md:px-6">
                <div className="max-w-5xl mx-auto">
                  <SelectedContextBar />
                </div>
              </div>
              <ChatInput onSend={handleSend} disabled={isLoading || isPending} />
            </>
          )}
        </div>
      </div>

    </div>
  );
}
