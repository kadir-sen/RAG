import { useRef, useState, type KeyboardEvent, type ChangeEvent } from 'react';

interface Props {
  placeholder?: string;
  ariaLabel?: string;
  inputId?: string;
  autoFocus?: boolean;
  onSubmit: (text: string) => void;
}

/**
 * Minimal single-line composer. No leading icon, no hotkey hint, no labelled
 * "send" button. The `→` glyph fades in on the right only when there is
 * content to send, matching the reference mockup.
 */
export default function EngineeringInputBar({
  placeholder = 'Ask anything…',
  ariaLabel = 'Ask the assistant',
  inputId,
  autoFocus,
  onSubmit,
}: Props) {
  const ref = useRef<HTMLInputElement>(null);
  const [hasText, setHasText] = useState(false);

  const submit = () => {
    const value = ref.current?.value.trim();
    if (!value) return;
    onSubmit(value);
    if (ref.current) ref.current.value = '';
    setHasText(false);
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      submit();
    }
  };

  const onChange = (e: ChangeEvent<HTMLInputElement>) => {
    setHasText(e.target.value.trim().length > 0);
  };

  return (
    <div className="flex items-center gap-2 bg-[var(--bg-surface)] border border-[var(--border)] rounded-[10px] focus-within:border-[var(--border-light)] transition-colors px-4 py-2.5">
      <label htmlFor={inputId} className="sr-only">
        {ariaLabel}
      </label>
      <input
        id={inputId}
        ref={ref}
        type="text"
        placeholder={placeholder}
        onKeyDown={onKey}
        onChange={onChange}
        className="flex-1 min-w-0 bg-transparent py-1.5 text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none text-sm md:text-base"
        autoFocus={autoFocus}
      />
      <button
        onClick={submit}
        aria-label="Send message"
        tabIndex={hasText ? 0 : -1}
        className={`shrink-0 w-7 h-7 flex items-center justify-center rounded-md text-[var(--text-muted)] hover:text-[var(--accent)] transition-opacity duration-150 ${hasText ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}
      >
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <line x1="5" y1="12" x2="19" y2="12" />
          <polyline points="12 5 19 12 12 19" />
        </svg>
      </button>
    </div>
  );
}
