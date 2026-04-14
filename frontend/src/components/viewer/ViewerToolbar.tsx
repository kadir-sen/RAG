interface Props {
  fileName: string;
  page?: number;
  totalPages?: number;
  onPrev?: () => void;
  onNext?: () => void;
  onClose: () => void;
  onExport?: () => void;
}

export default function ViewerToolbar({
  fileName,
  page,
  totalPages,
  onPrev,
  onNext,
  onClose,
  onExport,
}: Props) {
  return (
    <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-[var(--border)] bg-[var(--bg-surface)] shrink-0">
      <span className="text-xs text-[var(--text-primary)] truncate min-w-0 flex-1">
        {fileName}
      </span>
      <div className="flex items-center gap-1.5 flex-shrink-0">
        {page != null && totalPages != null && totalPages > 1 && (
          <>
            <button
              onClick={onPrev}
              disabled={page <= 1}
              aria-label="Previous page"
              className="w-7 h-7 rounded flex items-center justify-center text-xs bg-[var(--bg-hover)] text-[var(--text-primary)] disabled:opacity-30"
            >
              <svg aria-hidden="true" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="M7 2L3 6l4 4" /></svg>
            </button>
            <span className="text-[10px] text-[var(--text-secondary)] tabular-nums whitespace-nowrap">
              {page}/{totalPages}
            </span>
            <button
              onClick={onNext}
              disabled={page >= totalPages}
              aria-label="Next page"
              className="w-7 h-7 rounded flex items-center justify-center text-xs bg-[var(--bg-hover)] text-[var(--text-primary)] disabled:opacity-30"
            >
              <svg aria-hidden="true" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="M5 2l4 4-4 4" /></svg>
            </button>
          </>
        )}
        {onExport && (
          <button
            onClick={onExport}
            className="px-2 py-1 rounded text-[10px] bg-[var(--accent)]/20 text-[var(--accent)] hover:bg-[var(--accent)]/30 transition-colors whitespace-nowrap"
          >
            Export
          </button>
        )}
        <button
          onClick={onClose}
          aria-label="Close viewer"
          className="w-7 h-7 rounded-lg flex items-center justify-center bg-[var(--bg-hover)] text-[var(--text-secondary)] hover:bg-[var(--danger)] hover:text-white transition-colors"
        >
          <svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="4" y1="4" x2="12" y2="12" />
            <line x1="12" y1="4" x2="4" y2="12" />
          </svg>
        </button>
      </div>
    </div>
  );
}
