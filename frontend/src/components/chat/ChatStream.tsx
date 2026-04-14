import { useRef, useEffect } from 'react';
import type { Message } from '../../types/chat';
import type { ViewerDoc } from '../../stores/uiStore';
import MessageItem from './MessageItem';
import TypingIndicator from './TypingIndicator';

interface Props {
  messages: Message[];
  isLoading: boolean;
  onDocClick: (doc: ViewerDoc) => void;
  onRetry?: (text: string) => void;
}

export default function ChatStream({ messages, isLoading, onDocClick, onRetry }: Props) {
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
        {messages.map((msg) => (
          <MessageItem key={msg.id} message={msg} onDocClick={onDocClick} onRetry={onRetry} />
        ))}
        <TypingIndicator visible={isLoading} />
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
