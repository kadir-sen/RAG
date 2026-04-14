import { useState, useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getLibrary } from '../../api/libraryApi';
import type { LibraryDocument } from '../../types/api';
import Badge from '../shared/Badge';

interface Props {
  open: boolean;
  onClose: () => void;
  existingDocIds: string[];
  onAdd: (docIds: string[]) => void;
}

export default function LibraryPickerModal({ open, onClose, existingDocIds, onAdd }: Props) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  const { data: library = [], isLoading } = useQuery({
    queryKey: ['library'],
    queryFn: getLibrary,
    enabled: open,
    staleTime: 60_000,
  });

  useEffect(() => {
    if (open) setSelected(new Set());
  }, [open]);

  // Focus trap and Escape key handling
  useEffect(() => {
    if (!open) return;

    previousFocusRef.current = document.activeElement as HTMLElement;

    const timer = setTimeout(() => {
      dialogRef.current?.querySelector<HTMLElement>('button, input')?.focus();
    }, 50);

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
        return;
      }
      if (e.key === 'Tab' && dialogRef.current) {
        const focusable = dialogRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      clearTimeout(timer);
      document.removeEventListener('keydown', handleKeyDown);
      previousFocusRef.current?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  const toggle = (docId: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(docId)) next.delete(docId);
      else next.add(docId);
      return next;
    });
  };

  const handleAdd = () => {
    onAdd(Array.from(selected));
    onClose();
  };

  const extIcon = (ext: string) => {
    if (ext.includes('pdf')) return 'PDF';
    if (ext.includes('xls') || ext.includes('csv')) return 'Excel';
    if (ext.includes('eml') || ext.includes('msg')) return 'Email';
    return 'Doc';
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="library-picker-title"
        className="bg-[var(--bg-secondary)] rounded-lg border border-[var(--border)] w-full max-w-lg max-h-[85dvh] sm:max-h-[70vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        <div className="px-4 py-3 border-b border-[var(--border)] flex items-center justify-between">
          <h3 id="library-picker-title" className="text-[var(--text-primary)] font-medium">Add Documents</h3>
          <button onClick={onClose} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]">
            &times;
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-1">
          {isLoading ? (
            <p className="text-[var(--text-muted)] text-sm p-4">Loading library...</p>
          ) : library.length === 0 ? (
            <p className="text-[var(--text-muted)] text-sm p-4">No documents available. Upload files first.</p>
          ) : (
            library.map((doc: LibraryDocument) => {
              const alreadyAdded = existingDocIds.includes(doc.doc_id);
              const isSelected = selected.has(doc.doc_id);
              return (
                <label
                  key={doc.doc_id}
                  className={`flex items-center gap-3 p-2 rounded cursor-pointer hover:bg-[var(--bg-primary)] ${
                    alreadyAdded ? 'opacity-50 cursor-not-allowed' : ''
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={alreadyAdded || isSelected}
                    disabled={alreadyAdded}
                    onChange={() => !alreadyAdded && toggle(doc.doc_id)}
                    className="accent-[var(--accent)]"
                  />
                  <Badge label={extIcon(doc.extension)} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-[var(--text-primary)] truncate">{doc.file_name}</p>
                    <p className="text-xs text-[var(--text-muted)]">
                      {doc.file_size_kb} KB
                      {doc.table_names.length > 0 && ` · ${doc.table_names.length} tables`}
                    </p>
                    {doc.notice_metadata && (doc.notice_metadata.sender || doc.notice_metadata.date) && (
                      <p className="text-[10px] text-[var(--text-muted)] truncate">
                        {[
                          doc.notice_metadata.date,
                          doc.notice_metadata.sender && `From: ${doc.notice_metadata.sender}`,
                          doc.notice_metadata.recipient && `To: ${doc.notice_metadata.recipient}`,
                        ].filter(Boolean).join(' \u00b7 ')}
                      </p>
                    )}
                  </div>
                  {alreadyAdded && (
                    <span className="text-xs text-[var(--text-muted)]">Added</span>
                  )}
                </label>
              );
            })
          )}
        </div>

        <div className="px-4 py-3 border-t border-[var(--border)] flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm text-[var(--text-muted)] hover:text-[var(--text-primary)]"
          >
            Cancel
          </button>
          <button
            onClick={handleAdd}
            disabled={selected.size === 0}
            className="px-3 py-1.5 text-sm bg-[var(--accent)] text-white rounded disabled:opacity-40"
          >
            Add {selected.size > 0 ? `(${selected.size})` : ''}
          </button>
        </div>
      </div>
    </div>
  );
}
