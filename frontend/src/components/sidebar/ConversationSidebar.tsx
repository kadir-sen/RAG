import { useEffect, useState, useRef, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useConversations } from '../../hooks/useConversations';
import { useFiles } from '../../hooks/useFiles';
import { useChatStore } from '../../stores/chatStore';
import { useUIStore } from '../../stores/uiStore';
import { getExportUrl, getDocContent } from '../../api/fileApi';
import { getLibrary } from '../../api/libraryApi';
import { getConversation } from '../../api/conversationApi';
import type { ConversationMeta, LibraryDocument } from '../../types/api';
import type { Message } from '../../types/chat';
import { groupEmailsByParticipantPair } from '../../utils/emailGrouping';
import FileTypeBadge from '../ui/FileTypeBadge';
import SidebarSection from './SidebarSection';

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
      {typeof count === 'number' && (
        <span className="text-[11px] tabular-nums text-[var(--text-muted)]">{count}</span>
      )}
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
  const [viewingArchived, setViewingArchived] = useState(false);
  const {
    conversations,
    createConversation,
    deleteConversation,
    renameConversation,
    pinConversation,
    archiveConversation,
  } = useConversations({ archived: viewingArchived });
  const { files, uploadMultiple, uploading, isUploading } = useFiles();
  const { activeConversationId, setConversation, activeMode, setMode, selectedEmailIds, toggleEmailSelection, setSelectedEmails } = useChatStore();
  const { openDocument } = useUIStore();
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);

  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [switchingId, setSwitchingId] = useState<string | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
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

  const libraryQuery = useQuery({ queryKey: ['library'], queryFn: getLibrary, staleTime: 60_000 });

  // Auto-open the Correspondence folder when the user enters correspondence mode.
  useEffect(() => {
    if (activeMode === 'correspondence') {
      setOpenSections((prev) => (prev.correspondence ? prev : { ...prev, correspondence: true }));
    }
  }, [activeMode]);

  // Focus the search input when the search row is toggled open.
  useEffect(() => {
    if (searchOpen) searchInputRef.current?.focus();
  }, [searchOpen]);

  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [emailActionLoading, setEmailActionLoading] = useState(false);

  const trimmedQuery = searchQuery.trim().toLowerCase();
  const filtered = conversations.filter((c) => {
    if (!viewingArchived && c.conversation_id !== activeConversationId && c.message_count === 0) return false;
    if (trimmedQuery && !c.title.toLowerCase().includes(trimmedQuery)) return false;
    return true;
  });

  const handleNewChat = () => createConversation('New Chat');
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

  const emailDocs: LibraryDocument[] = (libraryQuery.data ?? [])
    .filter((d) => d.file_type === 'email' || d.extension === '.eml' || d.extension === '.msg');
  const emailGroups = groupEmailsByParticipantPair(emailDocs);

  const toggleGroupExpanded = (key: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleGroupSelection = (emailIds: string[], allSelected: boolean) => {
    if (allSelected) {
      setSelectedEmails(selectedEmailIds.filter((id) => !emailIds.includes(id)));
    } else {
      const merged = new Set(selectedEmailIds);
      emailIds.forEach((id) => merged.add(id));
      setSelectedEmails(Array.from(merged));
    }
  };

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

  return (
    <>
      {sidebarOpen && (
        <div className="fixed inset-0 bg-black/50 z-30 md:hidden" onClick={toggleSidebar} />
      )}
      <aside
        aria-label="Sidebar"
        aria-hidden={!sidebarOpen}
        className={`h-full md:h-full h-dvh bg-[var(--bg-secondary)] border-r border-[var(--border)] flex flex-col shrink-0 overflow-hidden transition-all duration-300 ease-in-out md:relative fixed md:z-auto z-40 top-0 left-0 ${
          sidebarOpen ? 'w-72' : 'w-0 border-r-0'
        }`}
      >
        {/* ── KNOWLEDGE BASE ─────────────────────────────────────── */}
        <SidebarSection title="Knowledge Base" />
        <div className="px-2 pt-1 pb-1 shrink-0 space-y-0.5">
          <SidebarItem
            icon={IconAIAssistant}
            label="AI Assistant"
            active={activeMode !== null}
            onClick={handleNewChat}
          />
          {/* AI Assistant sub-modes — always visible, indented like folder
              children so the mode picker reads as a property of AI Assistant
              rather than a stand-alone strip below the folders. */}
          <div className="ml-9 mr-2 border-l border-[var(--border)] pl-2 py-1 space-y-0.5">
            {(['document_analysis', 'correspondence'] as const).map((mode) => {
              const isActive = activeMode === mode;
              const label = mode === 'document_analysis' ? 'Document Analysis' : 'Correspondence';
              return (
                <button
                  key={mode}
                  type="button"
                  data-testid={`sidebar-mode-${mode}`}
                  aria-pressed={isActive}
                  onClick={() => setMode(mode)}
                  className={`w-full flex items-center gap-2 px-2 py-1 rounded text-left text-[12px] transition-colors ${
                    isActive
                      ? 'bg-[var(--bg-hover)] text-[var(--text-primary)]'
                      : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]'
                  }`}
                >
                  <span
                    aria-hidden="true"
                    className={`w-1.5 h-1.5 rounded-full ${isActive ? 'bg-[var(--accent)]' : 'bg-[var(--text-muted)]'}`}
                  />
                  <span className="flex-1 truncate">{label}</span>
                </button>
              );
            })}
          </div>
          <SidebarItem
            icon={IconDocuments}
            label="Documents"
            count={documentFiles.length}
            expandable
            ariaExpanded={openSections.documents}
            onClick={() => toggleSection('documents')}
          />
          {openSections.documents && (
            <div className="ml-9 mr-2 border-l border-[var(--border)] pl-2 py-1">
              {documentFiles.length === 0 ? (
                <p className="text-[11px] text-[var(--text-muted)] italic px-1 py-1">Empty</p>
              ) : (
                documentFiles.map((f) => (
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
          <SidebarItem
            icon={IconCorrespondence}
            label="Communications"
            count={emailDocs.length}
            expandable
            ariaExpanded={openSections.correspondence}
            onClick={() => toggleSection('correspondence')}
          />
          {openSections.correspondence && (
            <div className="ml-9 mr-2 border-l border-[var(--border)] pl-2 py-1 space-y-1">
              {emailDocs.length === 0 ? (
                <p className="text-[11px] text-[var(--text-muted)] italic px-1 py-1">
                  {libraryQuery.isLoading ? 'Loading…' : 'Empty'}
                </p>
              ) : (
                emailGroups.map((g) => {
                  const ids = g.emails.map((e) => e.doc_id);
                  const allSelected = ids.every((id) => selectedEmailIds.includes(id));
                  const someSelected = !allSelected && ids.some((id) => selectedEmailIds.includes(id));
                  const isExpanded = expandedGroups.has(g.key);
                  return (
                    <div key={g.key} className="rounded-md border border-[var(--border)] bg-[rgba(255,255,255,0.02)]">
                      <div className="flex items-center gap-2 px-2 py-1.5">
                        <button
                          type="button"
                          onClick={() => toggleGroupExpanded(g.key)}
                          aria-label={isExpanded ? 'Collapse' : 'Expand'}
                          className="text-[var(--text-muted)] hover:text-white shrink-0"
                        >
                          <svg width="10" height="10" viewBox="0 0 12 12" fill="none"
                            className={`transition-transform ${isExpanded ? 'rotate-90' : ''}`}>
                            <path d="M4 2l4 4-4 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        </button>
                        <button
                          type="button"
                          onClick={() => toggleGroupSelection(ids, allSelected)}
                          className="flex-1 text-left min-w-0"
                        >
                          <p className="text-[11px] text-[var(--text-primary)] truncate capitalize">{g.displayLabel}</p>
                          <p className="text-[10px] text-[var(--text-muted)]">
                            {g.emails.length} mail · {g.latestDate || '—'}
                          </p>
                        </button>
                        <input
                          type="checkbox"
                          checked={allSelected}
                          ref={(el) => { if (el) el.indeterminate = someSelected; }}
                          onChange={() => toggleGroupSelection(ids, allSelected)}
                          className="shrink-0"
                          aria-label="Select all emails in thread"
                        />
                      </div>
                      {isExpanded && (
                        <div className="px-2 pb-1.5 space-y-0.5 border-t border-[var(--border)]">
                          {g.emails.map((doc) => {
                            const isSelected = selectedEmailIds.includes(doc.doc_id);
                            const meta = doc.notice_metadata;
                            return (
                              <label
                                key={doc.doc_id}
                                className={`flex items-start gap-2 p-1.5 rounded cursor-pointer transition-colors ${
                                  isSelected ? 'bg-[var(--accent-glow)]' : 'hover:bg-[rgba(255,255,255,0.04)]'
                                }`}
                              >
                                <input
                                  type="checkbox"
                                  checked={isSelected}
                                  onChange={() => toggleEmailSelection(doc.doc_id)}
                                  className="mt-0.5"
                                />
                                <div className="min-w-0 flex-1">
                                  <p className="text-[11px] text-[var(--text-secondary)] truncate">{meta?.subject || doc.file_name}</p>
                                  <p className="text-[10px] text-[var(--text-muted)]">
                                    {meta?.date?.split('T')[0] || '—'} · {(meta?.sender || '').slice(0, 20)}
                                  </p>
                                </div>
                              </label>
                            );
                          })}
                        </div>
                      )}
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
            <div className="ml-9 mr-2 border-l border-[var(--border)] pl-2 py-1">
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

        {/* ── Email quick prompts (only in correspondence mode w/ selection) ── */}
        {activeMode === 'correspondence' && selectedEmailIds.length > 0 && (
          <div className="mx-3 mt-1 mb-2 space-y-1 pt-2 border-t border-[var(--border)] shrink-0">
            {QUICK_PROMPTS.map((qp) => (
              <button
                key={qp.label}
                onClick={() => handleEmailAction(qp.prompt)}
                disabled={emailActionLoading}
                className="w-full text-left px-2 py-1.5 rounded text-[10px] text-[var(--text-secondary)] hover:text-white hover:bg-[rgba(255,255,255,0.04)] transition-all disabled:opacity-30 disabled:cursor-not-allowed"
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
                        className="text-[10px] px-1.5 py-0.5 bg-[var(--danger)] text-white rounded"
                      >
                        Yes
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); cancelDelete(); }}
                        className="text-[10px] px-1.5 py-0.5 text-[var(--text-muted)] hover:text-white"
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
                            className={`p-0.5 hover:text-white ${c.pinned ? 'text-[var(--accent)]' : 'text-[var(--text-muted)]'}`}
                            title={c.pinned ? 'Unpin' : 'Pin'}
                          >
                            <svg width="10" height="10" viewBox="0 0 24 24" fill={c.pinned ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                              <path d="M12 2L9 8H4l4 4-2 8 6-4 6 4-2-8 4-4h-5z" />
                            </svg>
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); startRename(c); }}
                            className="p-0.5 text-[var(--text-muted)] hover:text-white"
                            title="Rename"
                          >
                            <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                              <path d="M7 2l3 3-6 6H1V8z" />
                            </svg>
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); archiveConversation({ id: c.conversation_id, archived: true }); }}
                            className="p-0.5 text-[var(--text-muted)] hover:text-white"
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
                          className="p-0.5 text-[var(--text-muted)] hover:text-white"
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
                <span className={u.status === 'completed' ? 'text-green-400' : u.status === 'error' ? 'text-red-400' : 'text-[var(--text-muted)]'}>
                  {u.status === 'completed' ? '✓' : u.status === 'error' ? '✗' : `${u.progress}%`}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* ── Bottom actions: minimal Add + Export ─────────────────── */}
        <div className="px-3 py-2 border-t border-[var(--border)] shrink-0 flex items-center justify-between gap-2">
          <button
            onClick={handleFileUpload}
            disabled={isUploading}
            aria-label="Add document"
            className="flex items-center gap-2 px-2.5 py-1.5 rounded-md text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors text-[12px] font-mono disabled:opacity-50"
          >
            {IconUpload}
            <span>{isUploading ? 'Uploading…' : 'Add document'}</span>
          </button>
          {files.length > 0 && (
            <a
              href={getExportUrl()}
              download
              aria-label="Export file list as CSV"
              className="font-mono text-[11px] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors px-2 py-1"
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
