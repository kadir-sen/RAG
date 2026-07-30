import { useRef, useEffect } from 'react';
import type { Message } from '../../types/chat';
import type { ViewerDoc } from '../../stores/uiStore';
import MessageItem from './MessageItem';
import ActivityFeed from './ActivityFeed';

interface Props {
  messages: Message[];
  isLoading: boolean;
  onDocClick: (doc: ViewerDoc) => void;
  onRetry?: (text: string) => void;
  activeRequestId?: string | null;
}

export default function ChatStream({ messages, isLoading, onDocClick, onRetry, activeRequestId }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const shouldAutoScroll = useRef(true);

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    shouldAutoScroll.current = el.scrollHeight - el.scrollTop - el.clientHeight < 150;
  };

  useEffect(() => {
    if (shouldAutoScroll.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages.length, isLoading]);

  if (!messages.length && !isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-sm text-[var(--text-muted)]">
        Start a conversation...
      </div>
    );
  }

  return (
    <div ref={containerRef} onScroll={handleScroll} className="flex-1 overflow-y-auto py-4 md:py-6" role="log" aria-label="Chat messages" aria-live="polite">
      <div className="max-w-5xl mx-auto px-2 md:px-6">
        {messages.map((msg, i) => (
          <MessageItem
            key={msg.id}
            message={msg}
            /* The question this answer replies to. The exported document is far
               more useful with it, and only this level knows the ordering. */
            question={
              msg.role === 'assistant'
                ? [...messages.slice(0, i)].reverse().find((m) => m.role === 'user')?.content ?? ''
                : ''
            }
            onDocClick={onDocClick}
            onRetry={onRetry}
          />
        ))}
        <ActivityFeed requestId={activeRequestId ?? null} visible={isLoading} />
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
