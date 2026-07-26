import { useQuery } from '@tanstack/react-query';
import { getLibrary } from '../../api/libraryApi';
import { useChatStore } from '../../stores/chatStore';
import type { LibraryDocument } from '../../types/api';

const QUICK_PROMPTS = [
  { label: 'Summarize selected emails', prompt: 'Summarize the key points and actions from these emails.' },
  { label: 'Draft a reply', prompt: 'Draft a professional reply to the most recent email in this thread.' },
  { label: 'Find key actions', prompt: 'List all action items, deadlines, and commitments from these emails.' },
];

interface Props {
  onSend: (text: string) => void;
}

export default function EmailSidebar({ onSend }: Props) {
  const { selectedEmailIds, toggleEmailSelection, setSelectedEmails } = useChatStore();

  const libraryQuery = useQuery({
    queryKey: ['library'],
    queryFn: getLibrary,
    staleTime: 60_000,
  });

  const emails = (libraryQuery.data ?? []).filter(
    (d: LibraryDocument) => d.file_type === 'email' || d.extension === '.eml' || d.extension === '.msg',
  );

  // Also include documents with notice metadata (letters, notices)
  const notices = (libraryQuery.data ?? []).filter(
    (d: LibraryDocument) => d.notice_extracted && d.file_type !== 'email',
  );

  const allDocs = [...emails, ...notices];
  const selectedCount = selectedEmailIds.length;

  return (
    <div className="w-72 flex flex-col border-l border-[var(--border)] bg-[var(--bg-secondary)] shrink-0 overflow-hidden">
      {/* Header */}
      <div className="px-3 py-3 border-b border-[var(--border)]">
        <h3 className="text-sm font-semibold text-[var(--text-primary)] flex items-center gap-2">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <rect x="2" y="4" width="20" height="16" rx="2" />
            <polyline points="22,7 12,13 2,7" />
          </svg>
          Correspondence
        </h3>
        <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
          {allDocs.length} email{allDocs.length !== 1 ? 's' : ''} / notices available
        </p>
      </div>

      {/* Email list */}
      <div className="flex-1 overflow-y-auto px-2 py-2">
        {libraryQuery.isLoading ? (
          <p className="text-xs text-[var(--text-muted)] text-center py-8">Loading...</p>
        ) : allDocs.length === 0 ? (
          <p className="text-xs text-[var(--text-muted)] text-center py-8">
            No emails uploaded yet. Upload .eml or .msg files.
          </p>
        ) : (
          allDocs.map((doc) => {
            const isSelected = selectedEmailIds.includes(doc.doc_id);
            const meta = doc.notice_metadata;
            const dateStr = meta?.date ? meta.date.split('T')[0] : '';
            const subject = meta?.subject || doc.file_name;

            return (
              <label
                key={doc.doc_id}
                className={`flex items-start gap-2.5 px-2 py-2.5 rounded-lg cursor-pointer transition-colors mb-0.5 ${
                  isSelected
                    ? 'bg-[var(--accent-glow)] border border-[var(--accent)]'
                    : 'hover:bg-[var(--bg-surface)] border border-transparent'
                }`}
              >
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={() => toggleEmailSelection(doc.doc_id)}
                  className="mt-0.5 rounded border-[var(--border)] bg-[var(--bg-surface)] text-[var(--accent)] focus:ring-[var(--accent)] flex-shrink-0"
                />
                <div className="min-w-0 flex-1">
                  <p className="text-xs text-[var(--text-primary)] truncate font-medium">
                    {subject.length > 50 ? subject.slice(0, 47) + '...' : subject}
                  </p>
                  {meta && (
                    <p className="text-[10px] text-[var(--text-muted)] truncate mt-0.5">
                      {[dateStr, meta.sender && `From: ${meta.sender.slice(0, 25)}`]
                        .filter(Boolean)
                        .join(' \u00b7 ')}
                    </p>
                  )}
                  {meta?.recipient && (
                    <p className="text-[10px] text-[var(--text-muted)] truncate">
                      To: {meta.recipient.slice(0, 30)}
                    </p>
                  )}
                </div>
              </label>
            );
          })
        )}
      </div>

      {/* Selection info + quick prompts */}
      <div className="px-3 py-3 border-t border-[var(--border)] space-y-2">
        {selectedCount > 0 && (
          <div className="flex items-center justify-between">
            <span className="text-xs text-[var(--accent)] font-medium">
              {selectedCount} selected
            </span>
            <button
              onClick={() => setSelectedEmails([])}
              className="text-[10px] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
            >
              Clear
            </button>
          </div>
        )}

        {QUICK_PROMPTS.map((qp) => (
          <button
            key={qp.label}
            onClick={() => onSend(qp.prompt)}
            disabled={selectedCount === 0}
            className="w-full text-left px-3 py-2 rounded-lg text-xs bg-[var(--bg-surface)] border border-[var(--border)] hover:border-[var(--border-light)] hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-all disabled:opacity-30 disabled:cursor-not-allowed"
          >
            {qp.label}
          </button>
        ))}
      </div>
    </div>
  );
}
