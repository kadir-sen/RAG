import { useRef, useState, useCallback, type KeyboardEvent } from 'react';
import { useAuthStore } from '../../stores/authStore';
import { count } from '../../utils/format';

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
  const user = useAuthStore((s) => s.user);

  // Token quota — used for a pre-flight warning so users aren't silently
  // blocked only after burning tokens (previously the badge just turned orange).
  const remainingPct = (() => {
    if (!user) return 100;
    if (user.plan_type === 'demo') {
      const p = Number(user.credit_percent_remaining);
      return Number.isFinite(p) ? Math.max(0, Math.min(100, p)) : 0;
    }
    const p = Number(user.percent_remaining);
    if (Number.isFinite(p)) return Math.max(0, Math.min(100, p));
    if (user.token_limit > 0) {
      return Math.max(0, Math.min(100, (1 - user.used_tokens / user.token_limit) * 100));
    }
    return 100;
  })();
  const quotaExhausted = remainingPct <= 0;
  const quotaLow = remainingPct > 0 && remainingPct < 20;
  const usedTokens = user?.used_tokens ?? 0;
  const tokenLimit = user?.token_limit ?? 0;
  const isDemo = user?.plan_type === 'demo';

  const handleSend = useCallback(() => {
    const text = inputRef.current?.value.trim() ?? '';
    if (!text || disabled || quotaExhausted) return;
    onSend(text);
    if (inputRef.current) {
      inputRef.current.value = '';
      inputRef.current.style.height = 'auto';
      inputRef.current.focus();
    }
    setHasText(false);
  }, [onSend, disabled, quotaExhausted]);

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
    <div className="flex-shrink-0 px-3 pt-2 pb-[max(0.75rem,env(safe-area-inset-bottom))] md:px-6 md:pt-3 md:pb-8">
      {(quotaExhausted || quotaLow) && (
        <div
          role={quotaExhausted ? 'alert' : 'status'}
          // The banner carries its state in the rule and the glyph, not in the
          // body text: --warning against paper measures 3.61:1, under AA for
          // text this size. Ink is 12.9:1 and it is what the sheet's own rule
          // ("emphasis is ink, not a colour") asks for anyway. --danger clears
          // AA at 7.1:1, so the exhausted case can keep speaking in red.
          className={`max-w-3xl mx-auto mb-2 rounded border px-3.5 py-2 text-xs flex items-center gap-2 bg-[var(--wash)] ${
            quotaExhausted
              ? 'border-[var(--danger)] text-[var(--danger)]'
              : 'border-[var(--warning)] text-[var(--text-primary)]'
          }`}
        >
          <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
            <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          <span>
            {quotaExhausted
              ? `${isDemo ? 'Credit balance' : 'Token quota'} fully used — new messages are paused. Contact your administrator to top up.`
              : `${isDemo ? 'Credit balance' : 'Token quota'} running low — ${remainingPct.toFixed(0)}% left.`}
            {isDemo ? (
              <span className="opacity-70">
                {' '}({user?.credits_remaining.toFixed(2)} credits left)
              </span>
            ) : tokenLimit > 0 && (
              <span className="opacity-70">
                {' '}({count(usedTokens)} / {count(tokenLimit)} tokens)
              </span>
            )}
          </span>
        </div>
      )}
      <div className="max-w-3xl mx-auto rounded-[2px] border border-[var(--border)] bg-[var(--bg-surface)] focus-within:border-[var(--ink)] transition-colors">
        <div className="flex items-end gap-2 px-3 py-3 md:px-5 md:py-4">
          <label htmlFor="chat-input" className="sr-only">Chat message</label>
          <textarea
            id="chat-input"
            ref={inputRef}
            rows={1}
            placeholder={quotaExhausted ? (isDemo ? 'Credit balance used up' : 'Token quota used up') : 'Ask anything…'}
            onKeyDown={handleKeyDown}
            onInput={handleInput}
            disabled={disabled || quotaExhausted}
            style={{ resize: 'none', overflow: 'hidden' }}
            className="min-w-0 flex-1 bg-transparent text-base text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none leading-7 disabled:opacity-60 md:text-[15px]"
            autoFocus
          />
          <button
            onClick={handleSend}
            disabled={disabled || !hasText || quotaExhausted}
            aria-label="Send message"
            tabIndex={hasText ? 0 : -1}
            className={`mb-0.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-[var(--text-muted)] hover:text-[var(--accent)] transition-opacity duration-150 ${hasText && !disabled && !quotaExhausted ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}
          >
            <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="5" y1="12" x2="19" y2="12" />
              <polyline points="12 5 19 12 12 19" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
