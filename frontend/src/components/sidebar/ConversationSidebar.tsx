import { useEffect, useState, useRef } from 'react';
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
import { getFileTypeBadge } from '../../styles/tokens';
import FileTypeBadge from '../ui/FileTypeBadge';

const ACCEPTED = '.pdf,.docx,.doc,.txt,.xlsx,.xls,.csv,.eml,.msg';

const QUICK_PROMPTS = [
  { label: 'Summarize selected emails', prompt: 'Summarize the key points and actions from these emails.' },
  { label: 'Draft a reply', prompt: 'Draft a professional reply to the most recent email in this thread.' },
  { label: 'Find key actions', prompt: 'List all action items, deadlines, and commitments from these emails.' },
];

interface SidebarProps { onSend?: (text: string) => void; }

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
  const { activeConversationId, setConversation, activeMode, selectedEmailIds, toggleEmailSelection, setSelectedEmails } = useChatStore();
  const { openDocument } = useUIStore();
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);

  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [switchingId, setSwitchingId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
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

  // Auto-open the Correspondence folder when the user enters correspondence mode
  useEffect(() => {
    if (activeMode === 'correspondence') {
      setOpenSections((prev) => (prev.correspondence ? prev : { ...prev, correspondence: true }));
    }
  }, [activeMode]);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [emailActionLoading, setEmailActionLoading] = useState(false);

  const trimmedQuery = searchQuery.trim().toLowerCase();
  const filtered = conversations.filter((c) => {
    if (!viewingArchived && c.conversation_id !== activeConversationId && c.message_count === 0) return false;
    if (trimmedQuery && !c.title.toLowerCase().includes(trimmedQuery)) return false;
    return true;
  });

  const handleNewChat = () => createConversation('New Chat');
  const handleSelect = async (id: string) => {
    if (editingId || switchingId) return;
    setSwitchingId(id);
    try {
      const conv = await getConversation(id);
      const msgs: Message[] = (conv.messages || []).map((m: { role: string; content: string; timestamp: string; response?: unknown }, i: number) => ({
        id: `h_${i}`, role: m.role as 'user' | 'assistant', content: m.content, timestamp: new Date(m.timestamp).getTime(), response: m.response,
      }));
      setConversation(id, msgs, conv.document_ids || []);
      if (typeof window !== 'undefined' && window.innerWidth < 768) toggleSidebar();
    } catch { setConversation(id); } finally { setSwitchingId(null); }
  };
  const startRename = (c: ConversationMeta) => { setEditingId(c.conversation_id); setEditTitle(c.title); };
  const commitRename = () => { if (editingId && editTitle.trim()) renameConversation({ id: editingId, title: editTitle.trim() }); setEditingId(null); };
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
  const onFilesSelected = () => { const selected = Array.from(fileInputRef.current?.files ?? []); if (selected.length) uploadMultiple(selected); if (fileInputRef.current) fileInputRef.current.value = ''; };

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


  return (
    <>
    {sidebarOpen && (
      <div className="fixed inset-0 bg-black/50 z-30 md:hidden" onClick={toggleSidebar} />
    )}
    <aside
      aria-label="Sidebar"
      aria-hidden={!sidebarOpen}
      className={`h-full md:h-full h-dvh bg-[var(--bg-secondary)] border-r border-[var(--border)] flex flex-col shrink-0 overflow-hidden transition-all duration-300 ease-in-out md:relative fixed md:z-auto z-40 top-0 left-0 ${sidebarOpen ? 'w-72' : 'w-0 border-r-0'}`}
    >
      {/* Header + New Chat */}
      <div className="p-3 shrink-0">
        <button onClick={handleNewChat}
          className="w-full bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white font-mono text-xs tracking-wide py-2 rounded-md flex items-center justify-center gap-2 transition-colors">
          <span aria-hidden="true" className="text-sm leading-none">+</span>
          New Chat
        </button>
      </div>

      {/* Search + archive toggle */}
      <div className="px-3 pb-2 shrink-0 space-y-1.5">
        <div className="relative">
          <span aria-hidden="true" className="absolute left-2.5 top-1/2 -translate-y-1/2 font-mono text-xs text-[var(--text-muted)]">⌕</span>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={viewingArchived ? 'Search archive…' : 'Search chats…'}
            aria-label="Search chats"
            className="w-full bg-[rgba(255,255,255,0.04)] border border-[var(--border)] rounded-md pl-7 pr-7 py-1.5 text-xs text-white placeholder-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]"
          />
          {searchQuery && (
            <button onClick={() => setSearchQuery('')} aria-label="Clear search"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-white">
              <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <line x1="2" y1="2" x2="10" y2="10" /><line x1="10" y1="2" x2="2" y2="10" />
              </svg>
            </button>
          )}
        </div>
        <button
          onClick={() => { setViewingArchived((v) => !v); setSearchQuery(''); }}
          className="w-full text-left font-mono text-[10px] tracking-wider text-[var(--text-muted)] hover:text-white transition-colors px-1"
        >
          {viewingArchived ? '← back to chats' : '↻ show archive'}
        </button>
      </div>

      {/* Chat list */}
      {filtered.length > 0 ? (
        <div className="px-3 pb-2 flex-1 min-h-0 overflow-y-auto">
          <p className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-muted)] mb-1.5 px-1">
            {viewingArchived ? 'Archived' : 'AI Assistant'}
          </p>
          {filtered.map((c) => {
            const isActive = c.conversation_id === activeConversationId;
            const isEditing = c.conversation_id === editingId;
            const isHovered = c.conversation_id === hoveredId;
            return (
              <div key={c.conversation_id}
                className={`flex items-center px-2.5 py-2 rounded-lg text-sm cursor-pointer transition-colors mb-0.5 ${isActive ? 'bg-[var(--bg-hover)] text-white' : 'text-[var(--text-secondary)] hover:text-white hover:bg-[rgba(255,255,255,0.04)]'}`}
                onClick={() => handleSelect(c.conversation_id)}
                onMouseEnter={() => setHoveredId(c.conversation_id)}
                onMouseLeave={() => { setHoveredId(null); if (pendingDeleteId === c.conversation_id) cancelDelete(); }}>
                {isEditing ? (
                  <input className="flex-1 bg-transparent text-xs text-white outline-none border-b border-[var(--accent)]"
                    value={editTitle} onChange={(e) => setEditTitle(e.target.value)} onBlur={commitRename}
                    onKeyDown={(e) => { if (e.key === 'Enter') commitRename(); if (e.key === 'Escape') setEditingId(null); }}
                    autoFocus onClick={(e) => e.stopPropagation()} />
                ) : pendingDeleteId === c.conversation_id ? (
                  <div className="flex items-center gap-1 flex-1">
                    <span className="text-xs text-[var(--danger)]">Delete?</span>
                    <button onClick={(e) => { e.stopPropagation(); confirmDelete(); }} className="text-[10px] px-1.5 py-0.5 bg-[var(--danger)] text-white rounded">Yes</button>
                    <button onClick={(e) => { e.stopPropagation(); cancelDelete(); }} className="text-[10px] px-1.5 py-0.5 text-[var(--text-muted)] hover:text-white">No</button>
                  </div>
                ) : (
                  <>
                    {c.pinned && !viewingArchived && (
                      <svg aria-hidden="true" width="9" height="9" viewBox="0 0 24 24" fill="currentColor"
                        className="mr-1 shrink-0 text-[var(--accent)]">
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
                        <button onClick={(e) => { e.stopPropagation(); pinConversation({ id: c.conversation_id, pinned: !c.pinned }); }}
                          className={`p-0.5 hover:text-white ${c.pinned ? 'text-[var(--accent)]' : 'text-[var(--text-muted)]'}`}
                          title={c.pinned ? 'Unpin' : 'Pin'}>
                          <svg width="10" height="10" viewBox="0 0 24 24" fill={c.pinned ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M12 2L9 8H4l4 4-2 8 6-4 6 4-2-8 4-4h-5z" />
                          </svg>
                        </button>
                        <button onClick={(e) => { e.stopPropagation(); startRename(c); }} className="p-0.5 text-[var(--text-muted)] hover:text-white" title="Rename">
                          <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="M7 2l3 3-6 6H1V8z" /></svg>
                        </button>
                        <button onClick={(e) => { e.stopPropagation(); archiveConversation({ id: c.conversation_id, archived: true }); }}
                          className="p-0.5 text-[var(--text-muted)] hover:text-white" title="Archive">
                          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <rect x="2" y="4" width="20" height="5" rx="1" /><path d="M4 9v10a1 1 0 001 1h14a1 1 0 001-1V9" /><line x1="10" y1="13" x2="14" y2="13" />
                          </svg>
                        </button>
                      </>
                    )}
                    {viewingArchived && (
                      <button onClick={(e) => { e.stopPropagation(); archiveConversation({ id: c.conversation_id, archived: false }); }}
                        className="p-0.5 text-[var(--text-muted)] hover:text-white" title="Unarchive">
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M21 8v13H3V8" /><rect x="1" y="3" width="22" height="5" /><path d="M10 12h4" /><path d="M9 16l3-3 3 3" />
                        </svg>
                      </button>
                    )}
                    <button onClick={(e) => { e.stopPropagation(); handleDelete(c.conversation_id); }} className="p-0.5 text-[var(--text-muted)] hover:text-[var(--danger)]" title="Delete">
                      <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="M2 3h8M4 3V2h4v1M5 5v4M7 5v4M3 3l.5 7h5l.5-7" /></svg>
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        (viewingArchived || trimmedQuery) && (
          <div className="px-3 pb-2 shrink-0">
            <p className="font-mono text-[11px] text-[var(--text-muted)] py-3 text-center">
              {trimmedQuery ? 'No results' : 'No archived chats'}
            </p>
          </div>
        )
      )}

      {/* Divider */}
      <div className="border-t border-[var(--border)]" />

      {/* Upload progress */}
      {uploading.length > 0 && (
        <div className="px-4 py-2 space-y-1 shrink-0">
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

      {/* Library folders: Documents / Correspondence / Spreadsheet */}
      {(() => {
        const documentFiles = files.filter((f) => {
          const t = (f.file_type || '').toLowerCase();
          return t === 'document' || t === 'pdf' || t === 'doc' || t === 'docx' || t === 'text' || t === 'txt';
        });
        const spreadsheetFiles = files.filter((f) => {
          const t = (f.file_type || '').toLowerCase();
          return t === 'data' || t === 'excel' || t === 'xls' || t === 'xlsx' || t === 'csv';
        });

        const FolderHeader = ({
          label,
          count,
          accent,
          open,
          onToggle,
        }: {
          label: string;
          count: number;
          accent: string;
          open: boolean;
          onToggle: () => void;
        }) => (
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={open}
            className="w-full flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-[rgba(255,255,255,0.04)] transition-colors text-left"
          >
            <svg
              width="10"
              height="10"
              viewBox="0 0 12 12"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className={`text-[var(--text-muted)] transition-transform ${open ? 'rotate-90' : ''}`}
            >
              <path d="M4 2l4 4-4 4" />
            </svg>
            <span
              className="w-1.5 h-1.5 rounded-full flex-shrink-0"
              style={{ background: accent }}
            />
            <span className="font-mono text-[11px] tracking-[0.14em] uppercase text-[var(--text-secondary)] flex-1">
              {label}
            </span>
            <span className="font-mono text-[10px] text-[var(--text-muted)] tabular-nums">{count}</span>
          </button>
        );

        return (
          <div className="flex flex-col flex-1 overflow-hidden px-3 py-2 min-h-0">
            <div className="flex-1 overflow-y-auto space-y-1.5 min-h-0">
              {/* Documents folder */}
              <div>
                <FolderHeader
                  label="Documents"
                  count={documentFiles.length}
                  accent={getFileTypeBadge('document').dot}
                  open={openSections.documents}
                  onToggle={() => toggleSection('documents')}
                />
                {openSections.documents && (
                  <div className="ml-3 mt-0.5 border-l border-[var(--border)] pl-1.5 py-1">
                    {documentFiles.length === 0 ? (
                      <p className="text-[10px] text-[var(--text-muted)] italic px-2 py-1.5">Empty</p>
                    ) : (
                      documentFiles.map((f) => (
                        <div
                          key={f.id}
                          onClick={() => openDocument({ docId: f.id, fileName: f.name })}
                          className="flex items-center gap-2 cursor-pointer hover:bg-[rgba(255,255,255,0.04)] px-1.5 py-1 rounded transition-colors group"
                        >
                          <FileTypeBadge fileType={f.file_type} />
                          <span className="text-[11px] truncate text-[var(--text-muted)] group-hover:text-[var(--text-secondary)] flex-1">
                            {f.name}
                          </span>
                        </div>
                      ))
                    )}
                  </div>
                )}
              </div>

              {/* Correspondence folder */}
              <div>
                <FolderHeader
                  label="Correspondence"
                  count={emailDocs.length}
                  accent={getFileTypeBadge('email').dot}
                  open={openSections.correspondence}
                  onToggle={() => toggleSection('correspondence')}
                />
                {openSections.correspondence && (
                  <div className="ml-3 mt-0.5 border-l border-[var(--border)] pl-1.5 py-1 space-y-1">
                    {emailDocs.length === 0 ? (
                      <p className="text-[10px] text-[var(--text-muted)] italic px-2 py-1.5">
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
                                <p className="text-xs text-[var(--text-primary)] truncate capitalize">
                                  {g.displayLabel}
                                </p>
                                <p className="text-[10px] text-[var(--text-muted)]">
                                  {g.emails.length} mail · son: {g.latestDate || '—'}
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
                                    <label key={doc.doc_id}
                                      className={`flex items-start gap-2 p-1.5 rounded cursor-pointer transition-colors ${isSelected ? 'bg-[var(--accent-glow)]' : 'hover:bg-[rgba(255,255,255,0.04)]'}`}>
                                      <input
                                        type="checkbox"
                                        checked={isSelected}
                                        onChange={() => toggleEmailSelection(doc.doc_id)}
                                        className="mt-0.5"
                                      />
                                      <div className="min-w-0 flex-1">
                                        <p className="text-[11px] text-[var(--text-secondary)] truncate">
                                          {meta?.subject || doc.file_name}
                                        </p>
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
              </div>

              {/* Spreadsheet folder */}
              <div>
                <FolderHeader
                  label="Spreadsheet"
                  count={spreadsheetFiles.length}
                  accent={getFileTypeBadge('data').dot}
                  open={openSections.spreadsheet}
                  onToggle={() => toggleSection('spreadsheet')}
                />
                {openSections.spreadsheet && (
                  <div className="ml-3 mt-0.5 border-l border-[var(--border)] pl-1.5 py-1">
                    {spreadsheetFiles.length === 0 ? (
                      <p className="text-[10px] text-[var(--text-muted)] italic px-2 py-1.5">Empty</p>
                    ) : (
                      spreadsheetFiles.map((f) => (
                        <div
                          key={f.id}
                          onClick={() => openDocument({ docId: f.id, fileName: f.name })}
                          className="flex items-center gap-2 cursor-pointer hover:bg-[rgba(255,255,255,0.04)] px-1.5 py-1 rounded transition-colors group"
                        >
                          <FileTypeBadge fileType={f.file_type} />
                          <span className="text-[11px] truncate text-[var(--text-muted)] group-hover:text-[var(--text-secondary)] flex-1">
                            {f.name}
                          </span>
                        </div>
                      ))
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* Email quick prompts — only visible when in Correspondence mode AND selection exists */}
            {activeMode === 'correspondence' && selectedEmailIds.length > 0 && (
              <div className="space-y-1 pt-2 border-t border-[var(--border)] shrink-0 mt-2">
                {QUICK_PROMPTS.map((qp) => (
                  <button key={qp.label}
                    onClick={() => handleEmailAction(qp.prompt)}
                    disabled={emailActionLoading}
                    className="w-full text-left px-2 py-1.5 rounded text-[10px] text-[var(--text-secondary)] hover:text-white hover:bg-[rgba(255,255,255,0.04)] transition-all disabled:opacity-30 disabled:cursor-not-allowed">
                    {emailActionLoading ? 'Loading…' : `${qp.label} (${selectedEmailIds.length})`}
                  </button>
                ))}
              </div>
            )}
          </div>
        );
      })()}

      {/* Bottom actions — primary Add Files + dashed drop hint + tertiary Export link */}
      <div className="px-3 py-2.5 border-t border-[var(--border)] shrink-0 space-y-2">
        <div className="border border-dashed border-[var(--border)] rounded-md py-2 px-2 text-center">
          <p className="font-mono text-[10px] text-[var(--text-muted)] tracking-wider">↓ drop files here</p>
          <p className="font-mono text-[9px] text-[var(--text-muted)]/80 mt-0.5">.pdf .xlsx .csv .eml .msg</p>
        </div>
        <button onClick={handleFileUpload} disabled={isUploading}
          className="w-full bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white font-medium py-2.5 rounded-md flex items-center justify-center gap-2 transition-colors text-xs disabled:opacity-50 font-mono tracking-wide">
          <span aria-hidden="true">↑</span>
          {isUploading ? 'Uploading…' : 'Add Files'}
        </button>
        {files.length > 0 && (
          <div className="flex justify-center">
            <a href={getExportUrl()} download
              aria-label="Export file list as CSV"
              className="font-mono text-[11px] text-[var(--accent)] hover:text-[var(--accent-hover)] transition-colors flex items-center gap-1">
              <span aria-hidden="true">↓</span> Export CSV
            </a>
          </div>
        )}
        <input ref={fileInputRef} type="file" accept={ACCEPTED} multiple onChange={onFilesSelected} className="hidden" aria-label="Upload documents" />
      </div>
    </aside>
    </>
  );
}
