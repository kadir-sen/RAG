// Status / metadata pill — keeps prior `<Badge label="…" />` callsites working,
// but routes everything through CSS tokens (no more hardcoded Tailwind palette).

const TONE_BY_LABEL: Record<string, 'accent' | 'success' | 'warning' | 'danger' | 'muted'> = {
  // intents
  answer: 'accent',
  doc_list: 'accent',
  email_trace: 'accent',
  sql_result: 'success',
  // indexing status
  completed: 'success',
  indexing: 'accent',
  pending: 'muted',
  error: 'danger',
  // misc
  'low confidence': 'warning',
};

const TONE_CLASSES: Record<string, string> = {
  accent:  'text-[var(--accent)] bg-[var(--accent-glow)] border-[var(--accent)]/40',
  success: 'text-[var(--accent-green)] bg-[var(--wash)] border-[var(--accent-green)]/40',
  warning: 'text-[var(--warning)] bg-[var(--wash)] border-[var(--warning)]/40',
  danger:  'text-[var(--danger)] bg-[var(--wash)] border-[var(--danger)]/40',
  muted:   'text-[var(--text-secondary)] bg-[var(--wash)] border-[var(--border)]',
};

export default function Badge({ label }: { label: string }) {
  const tone = TONE_BY_LABEL[label.toLowerCase()] ?? 'muted';
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded font-mono text-[10px] tracking-wider uppercase border ${TONE_CLASSES[tone]}`}
    >
      {label}
    </span>
  );
}
