import type { ReactNode } from 'react';

type Tone = 'default' | 'accent' | 'muted' | 'warning';

interface Props {
  children: ReactNode;
  tone?: Tone;
  bracketed?: boolean;     // wraps children in [ … ]
  uppercase?: boolean;
  title?: string;
  className?: string;
}

const TONE_CLASSES: Record<Tone, string> = {
  default: 'text-[var(--text-primary)] border-[var(--border)] bg-[var(--wash)]',
  accent:  'text-[var(--accent)] border-[var(--accent)] bg-[var(--accent-glow)]',
  muted:   'text-[var(--text-secondary)] border-[var(--border)] bg-transparent',
  warning: 'text-[var(--warning)] border-[var(--warning)] bg-[var(--wash)]',
};

// Bracketed monospace chip used everywhere in the engineering-blueprint design:
//   [ XLS ]   MODE.01   CORRESPONDENCE   ⌘K
export default function MonoTag({
  children,
  tone = 'default',
  bracketed = false,
  uppercase = false,
  title,
  className = '',
}: Props) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 font-mono text-[10px] tracking-[0.12em] px-1.5 py-0.5 border rounded ${TONE_CLASSES[tone]} ${uppercase ? 'uppercase' : ''} ${className}`}
    >
      {bracketed ? <>[&nbsp;{children}&nbsp;]</> : children}
    </span>
  );
}
