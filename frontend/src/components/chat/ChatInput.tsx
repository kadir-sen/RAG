import { useRef, useCallback, type KeyboardEvent } from 'react';

interface Props {
  onSend: (text: string) => void;
  disabled?: boolean;
}

export default function ChatInput({ onSend, disabled }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSend = useCallback(() => {
    const text = inputRef.current?.value.trim();
    if (!text || disabled) return;
    onSend(text);
    if (inputRef.current) inputRef.current.value = '';
  }, [onSend, disabled]);

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="px-4 pb-4 md:px-6 md:pb-6 pt-0 flex-shrink-0">
      <div className="max-w-5xl mx-auto relative flex items-center">
        <label htmlFor="chat-input" className="sr-only">Chat message</label>
        <input
          id="chat-input"
          ref={inputRef}
          type="text"
          placeholder="Ask about equipment, manpower, progress..."
          onKeyDown={handleKeyDown}
          disabled={disabled}
          className="w-full bg-[var(--bg-surface)] border border-[var(--border)] text-[var(--text-primary)] placeholder-[var(--text-secondary)] rounded-xl py-3 md:py-4 pl-4 pr-14 focus:outline-none focus:ring-1 focus:ring-[var(--accent)] focus:border-[var(--accent)] text-sm transition-shadow"
          autoFocus
        />
        <button
          onClick={handleSend}
          disabled={disabled}
          aria-label="Send message"
          className="absolute right-2 top-1/2 -translate-y-1/2 bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white w-10 h-10 flex items-center justify-center rounded-lg transition-colors disabled:opacity-30"
        >
          <svg aria-hidden="true" className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
            <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z" />
          </svg>
        </button>
      </div>
    </div>
  );
}
