import MonoTag from '../ui/MonoTag';

interface MetaChip {
  label: string;
}

interface Props {
  fileName: string;
  page?: number;
  totalPages?: number;
  onPrev?: () => void;
  onNext?: () => void;
  onClose: () => void;
  onExport?: () => void;
  typeBadge?: { label: string; color: string };
  meta?: MetaChip[];      // small chips: "608 rows", "5 cols", "47 pages"
}

export default function ViewerToolbar({
  fileName,
  page,
  totalPages,
  onPrev,
  onNext,
  onClose,
  onExport,
  typeBadge,
  meta,
}: Props) {
  return (
    <div className="border-b border-[var(--border)] bg-[var(--bg-surface)] shrink-0">
      {/* Title row — bracketed monogram + filename + nav + close */}
      <div className="flex items-center justify-between gap-2 px-3 py-2.5">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          {typeBadge && (
            <span
              className="shrink-0 font-mono text-[10px] tracking-wider px-1.5 py-0.5 border rounded inline-flex items-center gap-1.5"
              style={{ borderColor: typeBadge.color, color: typeBadge.color }}
            >
              <span aria-hidden="true" className="w-1.5 h-1.5" style={{ background: typeBadge.color }} />
              {typeBadge.label}
            </span>
          )}
          <span className="text-sm font-medium text-[var(--text-primary)] truncate min-w-0">
            {fileName}
          </span>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {page != null && totalPages != null && totalPages > 1 && (
            <>
              <button
                onClick={onPrev}
                disabled={page <= 1}
                aria-label="Previous page"
                className="flex h-11 w-11 items-center justify-center rounded text-xs bg-[var(--bg-hover)] text-[var(--text-primary)] disabled:opacity-30 lg:h-8 lg:w-8"
              >
                <svg aria-hidden="true" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="M7 2L3 6l4 4" /></svg>
              </button>
              <span className="text-[10px] text-[var(--text-secondary)] tabular-nums whitespace-nowrap font-mono">
                {page}/{totalPages}
              </span>
              <button
                onClick={onNext}
                disabled={page >= totalPages}
                aria-label="Next page"
                className="flex h-11 w-11 items-center justify-center rounded text-xs bg-[var(--bg-hover)] text-[var(--text-primary)] disabled:opacity-30 lg:h-8 lg:w-8"
              >
                <svg aria-hidden="true" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="M5 2l4 4-4 4" /></svg>
              </button>
            </>
          )}
          {onExport && (
            <button
              onClick={onExport}
              className="px-2 py-1 rounded text-[10px] font-mono tracking-wide bg-[var(--accent-glow)] text-[var(--accent)] hover:bg-[var(--accent)] hover:text-[var(--accent-ink)] transition-colors whitespace-nowrap"
            >
              ↓ CSV
            </button>
          )}
          <button
            onClick={onClose}
            aria-label="Close viewer"
            data-viewer-close
            className="flex h-11 w-11 items-center justify-center rounded-lg bg-[var(--bg-hover)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--danger)] hover:text-[var(--accent-ink)] lg:h-8 lg:w-8"
          >
            <svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="4" y1="4" x2="12" y2="12" />
              <line x1="12" y1="4" x2="4" y2="12" />
            </svg>
          </button>
        </div>
      </div>
      {/* Optional meta chip bar — "608 rows · 5 cols · 47 pages" */}
      {meta && meta.length > 0 && (
        <div className="flex items-center gap-1.5 px-3 py-1.5 border-t border-dashed border-[var(--border)] overflow-x-auto">
          {meta.map((m) => (
            <MonoTag key={m.label} tone="muted">{m.label}</MonoTag>
          ))}
        </div>
      )}
    </div>
  );
}
