import { memo } from 'react';

type Variant = 'assistant' | 'user';

interface Props {
  variant: Variant;
  initials?: string;
}

/**
 * Speaker mark beside a message.
 *
 * Drawn as a registration square rather than a coloured bubble: the
 * assistant is an ink-filled block (it issues the answer), the reader is
 * a hairlined block (an annotation made on the sheet).
 */
function Avatar({ variant, initials }: Props) {
  const label = initials ?? (variant === 'assistant' ? 'A' : 'U');
  const assistant = variant === 'assistant';
  return (
    <div
      aria-hidden="true"
      className="shrink-0 grid place-items-center select-none font-mono text-[10px] font-bold tracking-wider"
      style={{
        width: 'var(--avatar-size)',
        height: 'var(--avatar-size)',
        borderRadius: 2,
        background: assistant ? 'var(--ink)' : 'transparent',
        border: `1px solid ${assistant ? 'var(--ink)' : 'var(--ink-soft)'}`,
        color: assistant ? 'var(--accent-ink)' : 'var(--text-secondary)',
      }}
    >
      {label}
    </div>
  );
}

export default memo(Avatar);
