import { useRef, useCallback, type KeyboardEvent } from 'react';

interface Props {
  onSend: (text: string) => void;
  disabled?: boolean;
}

export default function ChatInput({ onSend, disabled }: Props) {
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const resetHeight = () => {
    if (inputRef.current) inputRef.current.style.height = 'auto';
  };

  const handleSend = useCallback(() => {
    const text = inputRef.current?.value.trim();
    if (!text || disabled) return;
    onSend(text);
    if (inputRef.current) {
      inputRef.current.value = '';
      resetHeight();
      inputRef.current.focus();
    }
  }, [onSend, disabled]);

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInput = () => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  };

  return (
    <div className="px-4 pb-4 md:px-6 md:pb-6 pt-2 flex-shrink-0">
      <div className="max-w-5xl mx-auto relative flex items-end">
        <label htmlFor="chat-input" className="sr-only">Chat message</label>
        <textarea
          id="chat-input"
          ref={inputRef}
          rows={1}
          placeholder="Ask about equipment, manpower, progress..."
          onKeyDown={handleKeyDown}
          onInput={handleInput}
          disabled={disabled}
          style={{ resize: 'none', overflow: 'hidden' }}
          className="w-full bg-[var(--bg-surface)] border border-[var(--border)] text-[var(--text-primary)] placeholder-[var(--text-secondary)] rounded-xl py-3 md:py-4 pl-4 pr-14 focus:outline-none focus:ring-1 focus:ring-[var(--accent)] focus:border-[var(--accent)] text-sm transition-shadow"
          autoFocus
        />
        <button
          onClick={handleSend}
          disabled={disabled}
          aria-label="Send message"
          className="absolute right-2 bottom-1.5 md:bottom-2 bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white w-10 h-10 flex items-center justify-center rounded-lg transition-colors disabled:opacity-30"
        >
          <svg aria-hidden="true" className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
            <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z" />
          </svg>
        </button>
      </div>
    </div>
  );
}
