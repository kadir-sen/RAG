import { useEffect, useState, useRef, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import { useConversations } from '../../hooks/useConversations';
import { useFiles } from '../../hooks/useFiles';
import { useChatStore } from '../../stores/chatStore';
import { useUIStore } from '../../stores/uiStore';
import { getExportUrl, getDocContent } from '../../api/fileApi';
import { getLibrary } from '../../api/libraryApi';
import { getConversation } from '../../api/conversationApi';
import type { ConversationMeta, LibraryDocument } from '../../types/api';
import type { Message } from '../../types/chat';
import FileTypeBadge from '../ui/FileTypeBadge';
import SidebarSection from './SidebarSection';
import UsageRing from '../shared/UsageRing';
import { useProjectStore } from '../../stores/projectStore';

// Communications folder = emails only (.eml / .msg / file_type "email").
const isEmailDoc = (d: LibraryDocument) => {
  const t = (d.file_type || '').toLowerCase();
  const ext = (d.extension || '').toLowerCase();
  return t === 'email' || ext === '.eml' || ext === '.msg';
};

const ACCEPTED = '.pdf,.docx,.doc,.txt,.xlsx,.xls,.csv,.eml,.msg';

const QUICK_PROMPTS = [
  { label: 'Summarize selected emails', prompt: 'Summarize the key points and actions from these emails.' },
  { label: 'Draft a reply', prompt: 'Draft a professional reply to the most recent email in this thread.' },
  { label: 'Find key actions', prompt: 'List all action items, deadlines, and commitments from these emails.' },
];

interface SidebarProps { onSend?: (text: string) => void; }

// ── Top-level sidebar item ─────────────────────────────────────
// ChatGPT-style large primary action button used for the five fixed entries
// at the top of the rail (new chat, search, documents, correspondence,
// spreadsheet). Generous padding, icon-led layout, optional trailing count
// and expand chevron for the folder-style items.
interface SidebarItemProps {
  icon: ReactNode;
  label: string;
  count?: number;
  trailing?: ReactNode;
  ariaPressed?: boolean;
  ariaExpanded?: boolean;
  expandable?: boolean;
  active?: boolean;
  onClick?: () => void;
}

function SidebarItem({
  icon,
  label,
  count,
  trailing,
  ariaPressed,
  ariaExpanded,
  expandable,
  active,
  onClick,
}: SidebarItemProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={ariaPressed}
      aria-expanded={ariaExpanded}
      className={`group w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors text-left ${
        active
          ? 'bg-[var(--bg-hover)] text-[var(--text-primary)]'
          : 'text-[var(--text-primary)] hover:bg-[var(--bg-hover)]'
      }`}
    >
      <span className="w-5 h-5 flex items-center justify-center text-[var(--text-secondary)] group-hover:text-[var(--text-primary)] flex-shrink-0">
        {icon}
      </span>
      <span className="text-[14px] font-medium flex-1 truncate">{label}</span>
      {trailing ?? (typeof count === 'number' && (
        <span className="text-[11px] tabular-nums text-[var(--text-muted)]">{count}</span>
      ))}
      {expandable && (
        <svg
          width="10"
          height="10"
          viewBox="0 0 12 12"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={`text-[var(--text-muted)] transition-transform ${ariaExpanded ? 'rotate-90' : ''}`}
        >
          <path d="M4 2l4 4-4 4" />
        </svg>
      )}
    </button>
  );
}

// ── Icons (inline SVG, 20px) ───────────────────────────────────
const IconAIAssistant = (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 11.5a8.38 8.38 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.38 8.38 0 01-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.38 8.38 0 013.8-.9h.5a8.48 8.48 0 018 8v.5z" />
  </svg>
);
const IconDocuments = (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 3H6a2 2 0 00-2 2v14a2 2 0 002 2h12a2 2 0 002-2V9z" />
    <path d="M14 3v6h6" />
  </svg>
);
const IconCorrespondence = (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="5" width="18" height="14" rx="2" />
    <path d="M3 7l9 6 9-6" />
  </svg>
);
const IconSpreadsheet = (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M3 10h18" />
    <path d="M3 15h18" />
    <path d="M9 4v16" />
    <path d="M15 4v16" />
  </svg>
);
const IconUpload = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 5v12" />
    <path d="M6 11l6-6 6 6" />
    <path d="M5 19h14" />
  </svg>
);

export default function ConversationSidebar({ onSend }: SidebarProps) {
  const projectId = useProjectStore((state) => state.selectedProjectId);
  const [viewingArchived, setViewingArchived] = useState(false);
  const {
    conversations,
    deleteConversation,
    renameConversation,
    pinConversation,
    archiveConversation,
  } = useConversations({ archived: viewingArchived });
  const { files, uploadMultiple, uploading, isUploading } = useFiles();
  const { activeConversationId, setConversation, selectedIds, toggleSelection } = useChatStore();
  const { openDocument } = useUIStore();
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);

  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [switchingId, setSwitchingId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const loadErrorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [docSearch, setDocSearch] = useState('');
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [openSections, setOpenSections] = useState<Record<'documents' | 'correspondence' | 'spreadsheet', boolean>>({
    documents: false,
    correspondence: false,
    spreadsheet: false,
  });
  const toggleSection = (key: 'documents' | 'correspondence' | 'spreadsheet') =>
    setOpenSections((prev) => ({ ...prev, [key]: !prev[key] }));
  const fileInputRef = useRef<HTMLInputElement>(null);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);

  const libraryQuery = useQuery({ queryKey: ['library', projectId], queryFn: getLibrary, enabled: Boolean(projectId), staleTime: 60_000 });
  const queryClient = useQueryClient();

  const showLoadError = (message: string) => {
    setLoadError(message);
    if (loadErrorTimerRef.current) clearTimeout(loadErrorTimerRef.current);
    loadErrorTimerRef.current = setTimeout(() => setLoadError(null), 5000);
  };
  useEffect(() => () => {
    if (loadErrorTimerRef.current) clearTimeout(loadErrorTimerRef.current);
  }, []);

  // Focus the search input when the search row is toggled open.
  useEffect(() => {
    if (searchOpen) searchInputRef.current?.focus();
  }, [searchOpen]);

  const [emailActionLoading, setEmailActionLoading] = useState(false);

  const trimmedQuery = searchQuery.trim().toLowerCase();
  const filtered = conversations.filter((c) => {
    if (!viewingArchived && c.conversation_id !== activeConversationId && c.message_count === 0) return false;
    if (trimmedQuery && !c.title.toLowerCase().includes(trimmedQuery)) return false;
    return true;
  });

  // Reset to welcome state instead of eagerly creating a backend conversation.
  // The actual conversation gets created lazily in ChatPage.handleSend when
  // the user submits the first message — so the New Chat surface matches the
  // fresh-page-load welcome screen exactly (mode cards + intro composer).
  const handleNewChat = () => setConversation('');
  const handleSearchToggle = () => {
    setSearchOpen((v) => {
      const next = !v;
      if (!next) setSearchQuery('');
      return next;
    });
  };
  // Track the most recently requested conversation so a slow earlier fetch
  // can't stomp the state for a newer click. We compare ids before applying.
  const selectionTokenRef = useRef<string | null>(null);
  const handleSelect = async (id: string) => {
    if (editingId) return;
    selectionTokenRef.current = id;
    setSwitchingId(id);
    try {
      const conv = await getConversation(id);
      // A later click already moved on — drop this stale result.
      if (selectionTokenRef.current !== id) return;
      const msgs: Message[] = (conv.messages || []).map(
        (m: { role: string; content: string; timestamp: string; response?: unknown }, i: number) => ({
          id: `h_${i}`,
          role: m.role as 'user' | 'assistant',
          content: m.content,
          timestamp: new Date(m.timestamp).getTime(),
          response: m.response,
        }),
      );
      setConversation(id, msgs, conv.document_ids || []);
      if (typeof window !== 'undefined' && window.innerWidth < 768) toggleSidebar();
    } catch (err) {
      // Don't silently fall back to setConversation(id) with no messages —
      // that produces the "click opens WelcomeScreen" bug. Surface the error
      // and keep the previous conversation visible so the user can retry.
      if (selectionTokenRef.current === id) {
        console.error('[Sidebar] Failed to load conversation', id, err);
        const status = isAxiosError(err) ? err.response?.status : undefined;
        if (status === 404) {
          // The backend drops the ghost index entry on 404 — refetch so the
          // dead item disappears from the list.
          queryClient.invalidateQueries({ queryKey: ['conversations'] });
          showLoadError('This conversation is no longer available.');
        } else {
          showLoadError('Could not load conversation — please try again.');
        }
      }
    } finally {
      if (selectionTokenRef.current === id) {
        setSwitchingId(null);
      }
    }
  };
  const startRename = (c: ConversationMeta) => { setEditingId(c.conversation_id); setEditTitle(c.title); };
  const commitRename = () => {
    if (editingId && editTitle.trim()) renameConversation({ id: editingId, title: editTitle.trim() });
    setEditingId(null);
  };
  const handleDelete = (id: string) => setPendingDeleteId(id);
  const confirmDelete = () => {
    if (!pendingDeleteId) return;
    deleteConversation(pendingDeleteId);
    if (activeConversationId === pendingDeleteId && conversations.length > 1) {
      const other = conversations.find((c) => c.conversation_id !== pendingDeleteId);
      if (other) setConversation(other.conversation_id);
    }
    setPendingDeleteId(null);
  };
  const cancelDelete = () => setPendingDeleteId(null);
  const handleFileUpload = () => fileInputRef.current?.click();
  const onFilesSelected = () => {
    const selected = Array.from(fileInputRef.current?.files ?? []);
    if (selected.length) uploadMultiple(selected);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const emailDocs: LibraryDocument[] = (libraryQuery.data ?? []).filter(isEmailDoc);
  const emailDocsSorted = [...emailDocs].sort((a, b) =>
    (b.notice_metadata?.date || '').localeCompare(a.notice_metadata?.date || ''),
  );
  // Selected EMAILS only (the quick-prompt actions are email-specific even though
  // the unified selection can also hold documents).
  const selectedEmailIds = emailDocs
    .filter((d) => selectedIds.includes(d.doc_id))
    .map((d) => d.doc_id);

  const handleEmailAction = async (prompt: string) => {
    if (selectedEmailIds.length === 0 || !onSend || emailActionLoading) return;
    setEmailActionLoading(true);
    try {
      const contents = await Promise.all(
        selectedEmailIds.map(async (id) => {
          const meta = emailDocs.find((e) => e.doc_id === id)?.notice_metadata;
          const fileName = emailDocs.find((e) => e.doc_id === id)?.file_name || id;
          try {
            const data = await getDocContent(id);
            return { meta, text: data.text || '', fileName: data.file_name || fileName };
          } catch {
            return { meta, text: '', fileName };
          }
        }),
      );

      const bundle = contents
        .map((c, i) => {
          const m = c.meta;
          return (
            `--- Email ${i + 1} ---\n` +
            `Subject: ${m?.subject || c.fileName}\n` +
            `From: ${m?.sender || 'Unknown'}\n` +
            `To: ${m?.recipient || 'Unknown'}\n` +
            `Date: ${m?.date || 'Unknown'}\n\n` +
            c.text.slice(0, 2000)
          );
        })
        .join('\n\n');

      const fullPrompt = `${prompt}\n\nSelected emails (${selectedEmailIds.length}):\n\n${bundle}`;
      onSend(fullPrompt);
    } finally {
      setEmailActionLoading(false);
    }
  };

  // ── Library counts (drive the trailing badges on the folder buttons) ──
  const documentFiles = files.filter((f) => {
    const t = (f.file_type || '').toLowerCase();
    return t === 'document' || t === 'pdf' || t === 'doc' || t === 'docx' || t === 'text' || t === 'txt';
  });
  const spreadsheetFiles = files.filter((f) => {
    const t = (f.file_type || '').toLowerCase();
    return t === 'data' || t === 'excel' || t === 'xls' || t === 'xlsx' || t === 'csv';
  });

  // Flat list of document-type LibraryDocuments (excludes emails and data
  // files). Sorted alphabetically for deterministic UI.
  const documentLibraryDocs: LibraryDocument[] = (libraryQuery.data ?? [])
    .filter((d) => {
      const t = (d.file_type || '').toLowerCase();
      return t === 'document' || (t !== 'email' && t !== 'data');
    })
    .sort((a, b) => a.file_name.localeCompare(b.file_name));

  // Search filter + render cap. A large corpus (thousands of PDFs) is browsed by
  // typing; we render at most 500 rows so the DOM stays light. The search box
  // narrows the list, so the cap is rarely hit once the user types.
  const _docQuery = docSearch.trim().toLowerCase();
  const filteredDocumentDocs = (_docQuery
    ? documentLibraryDocs.filter((d) => d.file_name.toLowerCase().includes(_docQuery))
    : documentLibraryDocs
  ).slice(0, 500);

  return (
    <>
      {sidebarOpen && (
        <div className="fixed inset-0 bg-[var(--overlay)] z-30 md:hidden" onClick={toggleSidebar} />
      )}
      <aside
        aria-label="Sidebar"
        aria-hidden={!sidebarOpen}
        className={`fixed left-0 top-0 z-40 flex h-dvh max-w-full shrink-0 flex-col overflow-hidden border-r border-[var(--border)] bg-[var(--bg-secondary)] transition-all duration-300 ease-in-out md:relative md:z-auto md:h-full ${
          sidebarOpen ? 'w-[min(18rem,100vw)]' : 'w-0 border-r-0'
        }`}
      >
        {/* ── KNOWLEDGE BASE ─────────────────────────────────────── */}
        <SidebarSection title="Knowledge Base" />
        <div className="px-2 pt-1 pb-1 shrink-0 space-y-0.5">
          <SidebarItem
            icon={IconAIAssistant}
            label="AI Assistant"
            onClick={handleNewChat}
            trailing={<UsageRing size={18} showLabel showTokens />}
          />
          <SidebarItem
            icon={IconDocuments}
            label="Documents"
            count={documentFiles.length}
            expandable
            ariaExpanded={openSections.documents}
            onClick={() => toggleSection('documents')}
          />
          {openSections.documents && (
            <div className="ml-9 mr-2 border-l border-[var(--border)] pl-2 py-1 space-y-1">
              {/* Search box — filters the (potentially huge) document list. */}
              <input
                type="text"
                value={docSearch}
                onChange={(e) => setDocSearch(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Escape') setDocSearch(''); }}
                placeholder="Search documents…"
                aria-label="Search documents"
                className="w-full bg-[var(--bg-input)] border border-[var(--border)] rounded px-2 py-1 text-[11px] text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:border-[var(--border-light)]"
              />
              {/* Scrollable list — bounded height so a large corpus scrolls within
                  its own window instead of overflowing the sidebar. */}
              <div className="max-h-[50vh] overflow-y-auto pr-1 space-y-0.5">
                {filteredDocumentDocs.length === 0 ? (
                  <p className="text-[11px] text-[var(--text-muted)] italic px-1 py-1">
                    {libraryQuery.isLoading ? 'Loading…' : _docQuery ? 'No matches' : 'Empty'}
                  </p>
                ) : (
                  filteredDocumentDocs.map((d) => {
                    const isSelected = selectedIds.includes(d.doc_id);
                    return (
                      <div
                        key={d.doc_id}
                        className={`flex items-center gap-2 p-1.5 rounded transition-colors ${
                          isSelected ? 'bg-[var(--accent-glow)]' : 'hover:bg-[var(--bg-hover)]'
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleSelection(d.doc_id)}
                          onClick={(e) => e.stopPropagation()}
                          className="shrink-0"
                          aria-label={`Select ${d.file_name}`}
                        />
                        <button
                          type="button"
                          onClick={() => openDocument({ docId: d.doc_id, fileName: d.file_name })}
                          className="min-w-0 flex-1 flex items-center gap-2 text-left group"
                        >
                          <FileTypeBadge fileType={d.file_type} />
                          <span className="text-[11px] truncate text-[var(--text-muted)] group-hover:text-[var(--text-secondary)] flex-1">
                            {d.file_name}
                          </span>
                        </button>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          )}
          <SidebarItem
            icon={IconCorrespondence}
            label="Communications"
            count={emailDocs.length}
            expandable
            ariaExpanded={openSections.correspondence}
            onClick={() => toggleSection('correspondence')}
          />
          {openSections.correspondence && (
            <div className="ml-9 mr-2 border-l border-[var(--border)] pl-2 py-1 space-y-0.5 max-h-[50vh] overflow-y-auto pr-1">
              {emailDocs.length === 0 ? (
                <p className="text-[11px] text-[var(--text-muted)] italic px-1 py-1">
                  {libraryQuery.isLoading ? 'Loading…' : 'Empty'}
                </p>
              ) : (
                emailDocsSorted.map((doc) => {
                  const isSelected = selectedIds.includes(doc.doc_id);
                  const meta = doc.notice_metadata;
                  return (
                    <div
                      key={doc.doc_id}
                      className={`flex items-start gap-2 p-1.5 rounded transition-colors ${
                        isSelected ? 'bg-[var(--accent-glow)]' : 'hover:bg-[var(--wash)]'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggleSelection(doc.doc_id)}
                        onClick={(e) => e.stopPropagation()}
                        className="mt-0.5 shrink-0"
                        aria-label="Select email for actions"
                      />
                      <button
                        type="button"
                        onClick={() => openDocument({ docId: doc.doc_id, fileName: meta?.subject || doc.file_name })}
                        className="min-w-0 flex-1 text-left cursor-pointer"
                      >
                        <p className="text-[11px] text-[var(--text-secondary)] truncate">{meta?.subject || doc.file_name}</p>
                        <p className="text-[10px] text-[var(--text-muted)]">
                          {meta?.date?.split('T')[0] || '—'} · {(meta?.sender || '').slice(0, 20)}
                        </p>
                      </button>
                    </div>
                  );
                })
              )}
            </div>
          )}
          <SidebarItem
            icon={IconSpreadsheet}
            label="Spreadsheets"
            count={spreadsheetFiles.length}
            expandable
            ariaExpanded={openSections.spreadsheet}
            onClick={() => toggleSection('spreadsheet')}
          />
          {openSections.spreadsheet && (
            <div className="ml-9 mr-2 border-l border-[var(--border)] pl-2 py-1 max-h-[50vh] overflow-y-auto pr-1">
              {spreadsheetFiles.length === 0 ? (
                <p className="text-[11px] text-[var(--text-muted)] italic px-1 py-1">Empty</p>
              ) : (
                spreadsheetFiles.map((f) => (
                  <button
                    key={f.id}
                    type="button"
                    onClick={() => openDocument({ docId: f.id, fileName: f.name })}
                    className="w-full flex items-center gap-2 px-1.5 py-1 rounded text-left hover:bg-[var(--bg-hover)] transition-colors group"
                  >
                    <FileTypeBadge fileType={f.file_type} />
                    <span className="text-[11px] truncate text-[var(--text-muted)] group-hover:text-[var(--text-secondary)] flex-1">
                      {f.name}
                    </span>
                  </button>
                ))
              )}
            </div>
          )}
        </div>

        {/* Document Analysis / Correspondence mode rows now live inline
            beneath the AI Assistant entry above, so the bottom toggle bar
            is no longer needed. */}

        {/* ── Email quick prompts (shown whenever emails are selected) ── */}
        {selectedEmailIds.length > 0 && (
          <div className="mx-3 mt-1 mb-2 space-y-1 pt-2 border-t border-[var(--border)] shrink-0">
            {QUICK_PROMPTS.map((qp) => (
              <button
                key={qp.label}
                onClick={() => handleEmailAction(qp.prompt)}
                disabled={emailActionLoading}
                className="w-full text-left px-2 py-1.5 rounded text-[10px] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--wash)] transition-all disabled:opacity-30 disabled:cursor-not-allowed"
              >
                {emailActionLoading ? 'Loading…' : `${qp.label} (${selectedEmailIds.length})`}
              </button>
            ))}
          </div>
        )}

        {/* ── Recent queries header (with inline search + archive toggle) ── */}
        <SidebarSection
          title={viewingArchived ? 'Archive' : 'Recent Queries'}
          trailing={
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleSearchToggle}
                aria-label={searchOpen ? 'Close search' : 'Search recent queries'}
                aria-pressed={searchOpen}
                className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="11" cy="11" r="7" />
                  <path d="M20 20l-3.5-3.5" />
                </svg>
              </button>
              <button
                type="button"
                onClick={() => { setViewingArchived((v) => !v); setSearchQuery(''); }}
                className="font-mono text-[10px] tracking-wider text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
              >
                {viewingArchived ? '← back' : 'archive'}
              </button>
            </div>
          }
        />
        {searchOpen && (
          <div className="px-3 pt-1 pb-1">
            <input
              ref={searchInputRef}
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Escape') handleSearchToggle(); }}
              placeholder={viewingArchived ? 'Search archive…' : 'Search chats…'}
              aria-label="Search chats"
              className="w-full bg-[var(--bg-input)] border border-[var(--border)] rounded-md px-2.5 py-1.5 text-xs text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:border-[var(--border-light)]"
            />
          </div>
        )}

        {loadError && (
          <div
            role="alert"
            className="mx-3 mb-1 px-2.5 py-1.5 rounded-md text-[11px] bg-[rgba(var(--accent-rgb),0.12)] text-[var(--accent)] border border-[rgba(var(--accent-rgb),0.35)]"
          >
            {loadError}
          </div>
        )}

        {/* ── Recent chats (scrollable, fills remaining height) ─────── */}
        <div className="flex-1 min-h-0 overflow-y-auto px-2 pb-2">
          {filtered.length === 0 ? (
            <p className="text-[11px] text-[var(--text-muted)] py-4 px-3 text-center">
              {trimmedQuery ? 'No matching chats' : viewingArchived ? 'No archived chats' : 'No chats yet'}
            </p>
          ) : (
            filtered.map((c) => {
              const isActive = c.conversation_id === activeConversationId;
              const isEditing = c.conversation_id === editingId;
              const isHovered = c.conversation_id === hoveredId;
              return (
                <div
                  key={c.conversation_id}
                  data-conv-id={c.conversation_id}
                  data-testid="conv-row"
                  className={`flex items-center px-3 py-2 rounded-lg text-[13px] cursor-pointer transition-colors mb-0.5 ${
                    isActive
                      ? 'bg-[var(--bg-hover)] text-[var(--text-primary)]'
                      : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]'
                  }`}
                  onClick={() => handleSelect(c.conversation_id)}
                  onMouseEnter={() => setHoveredId(c.conversation_id)}
                  onMouseLeave={() => {
                    setHoveredId(null);
                    if (pendingDeleteId === c.conversation_id) cancelDelete();
                  }}
                >
                  {isEditing ? (
                    <input
                      className="flex-1 bg-transparent text-[13px] text-[var(--text-primary)] outline-none border-b border-[var(--accent)]"
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      onBlur={commitRename}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') commitRename();
                        if (e.key === 'Escape') setEditingId(null);
                      }}
                      autoFocus
                      onClick={(e) => e.stopPropagation()}
                    />
                  ) : pendingDeleteId === c.conversation_id ? (
                    <div className="flex items-center gap-1 flex-1">
                      <span className="text-xs text-[var(--danger)]">Delete?</span>
                      <button
                        onClick={(e) => { e.stopPropagation(); confirmDelete(); }}
                        className="text-[10px] px-1.5 py-0.5 bg-[var(--danger)] text-[var(--accent-ink)] rounded"
                      >
                        Yes
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); cancelDelete(); }}
                        className="text-[10px] px-1.5 py-0.5 text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                      >
                        No
                      </button>
                    </div>
                  ) : (
                    <>
                      {c.pinned && !viewingArchived && (
                        <svg
                          aria-hidden="true"
                          width="9"
                          height="9"
                          viewBox="0 0 24 24"
                          fill="currentColor"
                          className="mr-1.5 shrink-0 text-[var(--accent)]"
                        >
                          <path d="M12 2L9 8H4l4 4-2 8 6-4 6 4-2-8 4-4h-5z" />
                        </svg>
                      )}
                      <span className="truncate flex-1">{c.title}</span>
                      {switchingId === c.conversation_id && (
                        <span className="ml-auto w-3 h-3 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
                      )}
                    </>
                  )}
                  {!isEditing && pendingDeleteId !== c.conversation_id && isHovered && !switchingId && (
                    <div className="flex items-center gap-0.5 ml-1">
                      {!viewingArchived && (
                        <>
                          <button
                            onClick={(e) => { e.stopPropagation(); pinConversation({ id: c.conversation_id, pinned: !c.pinned }); }}
                            className={`p-0.5 hover:text-[var(--text-primary)] ${c.pinned ? 'text-[var(--accent)]' : 'text-[var(--text-muted)]'}`}
                            title={c.pinned ? 'Unpin' : 'Pin'}
                          >
                            <svg width="10" height="10" viewBox="0 0 24 24" fill={c.pinned ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                              <path d="M12 2L9 8H4l4 4-2 8 6-4 6 4-2-8 4-4h-5z" />
                            </svg>
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); startRename(c); }}
                            className="p-0.5 text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                            title="Rename"
                          >
                            <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                              <path d="M7 2l3 3-6 6H1V8z" />
                            </svg>
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); archiveConversation({ id: c.conversation_id, archived: true }); }}
                            className="p-0.5 text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                            title="Archive"
                          >
                            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                              <rect x="2" y="4" width="20" height="5" rx="1" />
                              <path d="M4 9v10a1 1 0 001 1h14a1 1 0 001-1V9" />
                              <line x1="10" y1="13" x2="14" y2="13" />
                            </svg>
                          </button>
                        </>
                      )}
                      {viewingArchived && (
                        <button
                          onClick={(e) => { e.stopPropagation(); archiveConversation({ id: c.conversation_id, archived: false }); }}
                          className="p-0.5 text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                          title="Unarchive"
                        >
                          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M21 8v13H3V8" />
                            <rect x="1" y="3" width="22" height="5" />
                            <path d="M10 12h4" />
                            <path d="M9 16l3-3 3 3" />
                          </svg>
                        </button>
                      )}
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDelete(c.conversation_id); }}
                        className="p-0.5 text-[var(--text-muted)] hover:text-[var(--danger)]"
                        title="Sil"
                      >
                        <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                          <path d="M2 3h8M4 3V2h4v1M5 5v4M7 5v4M3 3l.5 7h5l.5-7" />
                        </svg>
                      </button>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>

        {/* ── Upload progress (live indicator) ─────────────────────── */}
        {uploading.length > 0 && (
          <div className="px-4 py-2 space-y-1 shrink-0 border-t border-[var(--border)]">
            {uploading.map((u) => (
              <div key={u.name} className="flex items-center gap-2 text-[10px]">
                <span className="truncate flex-1 text-[var(--text-secondary)]">{u.name}</span>
                <span className={u.status === 'completed' ? 'text-[var(--accent-green)]' : u.status === 'error' ? 'text-[var(--danger)]' : 'text-[var(--text-muted)]'}>
                  {u.status === 'completed' ? '✓' : u.status === 'error' ? '✗' : `${u.progress}%`}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* ── Bottom actions: prominent Add + small Export ─────────────── */}
        <div className="px-3 pt-2.5 pb-3.5 border-t border-[var(--border)] shrink-0 flex items-center gap-2">
          <button
            onClick={handleFileUpload}
            disabled={isUploading}
            aria-label="Add document"
            className="flex-1 flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg border border-[var(--border)] text-[var(--text-primary)] hover:border-[var(--accent)] hover:bg-[var(--bg-hover)] transition-colors text-[13px] font-medium disabled:opacity-50"
          >
            {IconUpload}
            <span>{isUploading ? 'Uploading…' : 'Add document'}</span>
          </button>
          {files.length > 0 && (
            <a
              href={getExportUrl()}
              download
              aria-label="Export file list as CSV"
              className="shrink-0 font-mono text-[11px] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors px-2 py-2.5"
            >
              ↓ CSV
            </a>
          )}
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPTED}
            multiple
            onChange={onFilesSelected}
            className="hidden"
            aria-label="Upload documents"
          />
        </div>
      </aside>
    </>
  );
}
