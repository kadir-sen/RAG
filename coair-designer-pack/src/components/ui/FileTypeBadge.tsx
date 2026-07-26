import { getFileTypeBadge } from '../../styles/tokens';

interface Props {
  fileType?: string | null;     // backend `file_type` (document/data/email/...) or extension
  extension?: string | null;    // optional override (.pdf/.xlsx/...)
  size?: 'sm' | 'md';
  className?: string;
}

// Bracketed monogram + 5px colored dot — the "AFTER" treatment in the
// design's badge-direction artboard. Replaces saturated office-2007 blocks.
export default function FileTypeBadge({
  fileType,
  extension,
  size = 'sm',
  className = '',
}: Props) {
  const badge = getFileTypeBadge(extension ?? fileType);
  const dotSize = size === 'sm' ? 'w-1.5 h-1.5' : 'w-2 h-2';
  const text = size === 'sm' ? 'text-[9px]' : 'text-[10px]';
  const padding = size === 'sm' ? 'px-1.5 py-0.5' : 'px-2 py-0.5';
  return (
    <span
      aria-label={`${badge.label} file`}
      className={`inline-flex items-center gap-1 shrink-0 ${padding} rounded font-mono ${text} font-semibold tracking-wider text-[var(--text-primary)] border border-[var(--border)] bg-[var(--wash)] ${className}`}
    >
      <span aria-hidden="true" className={`${dotSize}`} style={{ background: badge.dot }} />
      {badge.label}
    </span>
  );
}
