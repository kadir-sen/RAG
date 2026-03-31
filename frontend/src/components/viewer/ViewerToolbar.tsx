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
    <div className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--border)] bg-[var(--bg-surface)] shrink-0">
      <div className="flex items-center gap-2 min-w-0 flex-1">
        <span className="text-sm text-[var(--text-primary)] truncate">
          {fileName}
        </span>
      </div>
      <div className="flex items-center gap-2 flex-shrink-0">
        {page != null && totalPages != null && totalPages > 1 && (
          <>
            <button
              onClick={onPrev}
              disabled={page <= 1}
              className="px-2 py-1 rounded text-xs bg-[var(--bg-hover)] text-[var(--text-primary)] disabled:opacity-30"
            >
              Prev
            </button>
            <span className="text-xs text-[var(--text-secondary)]">
              {page}/{totalPages}
            </span>
            <button
              onClick={onNext}
              disabled={page >= totalPages}
              className="px-2 py-1 rounded text-xs bg-[var(--bg-hover)] text-[var(--text-primary)] disabled:opacity-30"
            >
              Next
            </button>
          </>
        )}
        {onExport && (
          <button
            onClick={onExport}
            className="px-2.5 py-1 rounded text-xs bg-[var(--accent)]/20 text-[var(--accent)] hover:bg-[var(--accent)]/30 transition-colors"
          >
            Export
          </button>
        )}
        <button
          onClick={onClose}
          className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--bg-hover)] text-[var(--text-secondary)] hover:bg-[var(--danger)] hover:text-white transition-colors"
          title="Close"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="4" y1="4" x2="12" y2="12" />
            <line x1="12" y1="4" x2="4" y2="12" />
          </svg>
        </button>
      </div>
    </div>
  );
}
