import { useRef, useState, useCallback, type KeyboardEvent } from 'react';

interface Props {
  onSend: (text: string) => void;
  disabled?: boolean;
}

/**
 * Minimal single-line composer. Auto-grows up to 200px. Enter sends,
 * Shift+Enter inserts a newline. The `→` glyph fades in only when there
 * is content to send.
 */
export default function ChatInput({ onSend, disabled }: Props) {
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [hasText, setHasText] = useState(false);

  const handleSend = useCallback(() => {
    const text = inputRef.current?.value.trim() ?? '';
    if (!text || disabled) return;
    onSend(text);
    if (inputRef.current) {
      inputRef.current.value = '';
      inputRef.current.style.height = 'auto';
      inputRef.current.focus();
    }
    setHasText(false);
  }, [onSend, disabled]);

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
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
    setHasText(el.value.trim().length > 0);
  };

  return (
    <div className="px-4 pb-4 md:px-6 md:pb-6 pt-2 flex-shrink-0">
      <div className="max-w-3xl mx-auto rounded-[10px] border border-[var(--border)] bg-[var(--bg-surface)] focus-within:border-[var(--border-light)] transition-colors">
        <div className="flex items-end gap-2 px-4 py-3">
          <label htmlFor="chat-input" className="sr-only">Chat message</label>
          <textarea
            id="chat-input"
            ref={inputRef}
            rows={1}
            placeholder="Ask anything…"
            onKeyDown={handleKeyDown}
            onInput={handleInput}
            disabled={disabled}
            style={{ resize: 'none', overflow: 'hidden' }}
            className="flex-1 bg-transparent text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none text-sm leading-6"
            autoFocus
          />
          <button
            onClick={handleSend}
            disabled={disabled || !hasText}
            aria-label="Send message"
            tabIndex={hasText ? 0 : -1}
            className={`shrink-0 w-7 h-7 mb-0.5 flex items-center justify-center rounded-md text-[var(--text-muted)] hover:text-[var(--accent)] transition-opacity duration-150 ${hasText && !disabled ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}
          >
            <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="5" y1="12" x2="19" y2="12" />
              <polyline points="12 5 19 12 12 19" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
