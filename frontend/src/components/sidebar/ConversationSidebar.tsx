import { useState, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useConversations } from '../../hooks/useConversations';
import { useFiles } from '../../hooks/useFiles';
import { useChatStore } from '../../stores/chatStore';
import { useUIStore } from '../../stores/uiStore';
import { getExportUrl } from '../../api/fileApi';
import { getLibrary } from '../../api/libraryApi';
import { getConversation } from '../../api/conversationApi';
import type { ConversationMeta, LibraryDocument } from '../../types/api';
import type { Message } from '../../types/chat';

const ACCEPTED = '.pdf,.docx,.doc,.txt,.xlsx,.xls,.csv,.eml,.msg';

const FILE_ICONS: Record<string, { bg: string; type: 'excel' | 'pdf' | 'email' | 'other' }> = {
  data:     { bg: 'bg-green-600', type: 'excel' },
  excel:    { bg: 'bg-green-600', type: 'excel' },
  document: { bg: 'bg-red-500',   type: 'pdf' },
  email:    { bg: 'bg-blue-500',  type: 'email' },
  unknown:  { bg: 'bg-gray-500',  type: 'other' },
};

const QUICK_PROMPTS = [
  { label: 'Summarize selected emails', prompt: 'Summarize the key points and actions from these emails.' },
  { label: 'Draft a reply', prompt: 'Draft a professional reply to the most recent email in this thread.' },
  { label: 'Find key actions', prompt: 'List all action items, deadlines, and commitments from these emails.' },
];

interface SidebarProps { onSend?: (text: string) => void; }

export default function ConversationSidebar({ onSend }: SidebarProps) {
  const { conversations, createConversation, deleteConversation, renameConversation } = useConversations();
  const { files, uploadMultiple, uploading, isUploading } = useFiles();
  const { activeConversationId, setConversation, activeMode, selectedEmailIds, toggleEmailSelection } = useChatStore();
  const { openDocument } = useUIStore();
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);

  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [switchingId, setSwitchingId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);

  const libraryQuery = useQuery({ queryKey: ['library'], queryFn: getLibrary, staleTime: 60_000, enabled: activeMode === 'correspondence' });

  const filtered = conversations.filter((c) => c.conversation_id === activeConversationId || c.message_count > 0);

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
    .filter((d) => d.file_type === 'email' || d.extension === '.eml' || d.extension === '.msg')
    .sort((a, b) => (a.notice_metadata?.date || '').localeCompare(b.notice_metadata?.date || ''));

  const FileIcon = ({ fileType }: { fileType: string }) => {
    const fi = FILE_ICONS[fileType] || FILE_ICONS.unknown;
    return (
      <div className={`w-6 h-6 shrink-0 ${fi.bg} rounded flex items-center justify-center`}>
        {fi.type === 'pdf' ? (
          <svg className="w-3.5 h-3.5 text-white" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" strokeLinecap="round" strokeLinejoin="round" /></svg>
        ) : fi.type === 'email' ? (
          <svg className="w-3.5 h-3.5 text-white" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M21.75 6.75v10.5a2.25 2.25 0 01-2.25 2.25h-15a2.25 2.25 0 01-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25m19.5 0v.243a2.25 2.25 0 01-1.07 1.916l-7.5 4.615a2.25 2.25 0 01-2.36 0L3.32 8.91a2.25 2.25 0 01-1.07-1.916V6.75" strokeLinecap="round" strokeLinejoin="round" /></svg>
        ) : (
          <span className="text-[9px] font-bold text-white">XLS</span>
        )}
      </div>
    );
  };

  return (
    <>
    {sidebarOpen && (
      <div className="fixed inset-0 bg-black/50 z-30 md:hidden" onClick={toggleSidebar} />
    )}
    <aside
      aria-label="Sidebar"
      aria-hidden={!sidebarOpen}
      className={`h-full md:h-full h-dvh bg-[var(--bg-secondary)] border-r border-[var(--border)] flex flex-col shrink-0 overflow-hidden transition-all duration-300 ease-in-out md:relative fixed md:z-auto z-40 top-0 left-0 ${sidebarOpen ? 'w-64' : 'w-0 border-r-0'}`}
    >
      {/* Header + New Chat */}
      <div className="p-4 shrink-0">
        <button onClick={handleNewChat}
          className="w-full bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white font-medium py-2 rounded-lg flex items-center justify-center gap-2 transition-colors text-sm">
          <svg aria-hidden="true" width="12" height="12" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
            <line x1="7" y1="2" x2="7" y2="12" /><line x1="2" y1="7" x2="12" y2="7" />
          </svg>
          New Chat
        </button>
      </div>

      {/* Chat list */}
      {filtered.length > 0 && (
        <div className="px-3 pb-2 shrink-0 max-h-36 overflow-y-auto">
          <p className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-1.5 px-1">Recent Chats</p>
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
                    <span className="truncate flex-1">{c.title}</span>
                    {switchingId === c.conversation_id && (
                      <span className="ml-auto w-3 h-3 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
                    )}
                  </>
                )}
                {!isEditing && pendingDeleteId !== c.conversation_id && isHovered && !switchingId && (
                  <div className="flex items-center gap-0.5 ml-1">
                    <button onClick={(e) => { e.stopPropagation(); startRename(c); }} className="p-0.5 text-[var(--text-muted)] hover:text-white" title="Rename">
                      <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="M7 2l3 3-6 6H1V8z" /></svg>
                    </button>
                    <button onClick={(e) => { e.stopPropagation(); handleDelete(c.conversation_id); }} className="p-0.5 text-[var(--text-muted)] hover:text-[var(--danger)]" title="Delete">
                      <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="M2 3h8M4 3V2h4v1M5 5v4M7 5v4M3 3l.5 7h5l.5-7" /></svg>
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
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

      {/* Documents or Correspondence */}
      {activeMode === 'correspondence' ? (
        <div className="flex flex-col flex-1 overflow-hidden px-3 py-2">
          <p className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-2 px-1">Emails ({emailDocs.length})</p>
          <div className="flex-1 overflow-y-auto space-y-0.5">
            {emailDocs.map((doc) => {
              const isSelected = selectedEmailIds.includes(doc.doc_id);
              const meta = doc.notice_metadata;
              return (
                <label key={doc.doc_id} className={`flex items-start gap-2 p-2 rounded-lg cursor-pointer transition-colors ${isSelected ? 'bg-[var(--accent-glow)]' : 'hover:bg-[rgba(255,255,255,0.04)]'}`}>
                  <input type="checkbox" checked={isSelected} onChange={() => toggleEmailSelection(doc.doc_id)} className="mt-0.5" />
                  <div className="min-w-0 flex-1">
                    <p className="text-xs text-[var(--text-secondary)] truncate">{meta?.subject || doc.file_name}</p>
                    <p className="text-[10px] text-[var(--text-muted)]">{[meta?.date?.split('T')[0], meta?.sender?.slice(0, 20)].filter(Boolean).join(' · ')}</p>
                  </div>
                </label>
              );
            })}
          </div>
          <div className="space-y-1 pt-2 border-t border-[var(--border)] shrink-0 mt-2">
            {QUICK_PROMPTS.map((qp) => (
              <button key={qp.label} onClick={() => onSend?.(qp.prompt)} disabled={selectedEmailIds.length === 0}
                className="w-full text-left px-2 py-1.5 rounded text-[10px] text-[var(--text-secondary)] hover:text-white hover:bg-[rgba(255,255,255,0.04)] transition-all disabled:opacity-30">{qp.label}</button>
            ))}
          </div>
        </div>
      ) : (
        <div className="flex flex-col flex-1 overflow-hidden px-3 py-2">
          <div className="mb-1 px-1 shrink-0">
            <p className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider">
              Documents {files.length > 0 && `(${files.length})`}
            </p>
          </div>

          {/* Type counts */}
          {files.length > 0 && (() => {
            const counts: Record<string, number> = {};
            for (const f of files) { counts[f.file_type || 'unknown'] = (counts[f.file_type || 'unknown'] || 0) + 1; }
            return (
              <div className="flex gap-3 mb-2 px-1 text-xs text-[var(--text-muted)] shrink-0">
                {counts['data'] && <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-green-500" />{counts['data']} excel</span>}
                {counts['document'] && <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-red-500" />{counts['document']} pdf</span>}
                {counts['email'] && <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-blue-500" />{counts['email']} mail</span>}
              </div>
            );
          })()}

          {/* File list - compact, scrollable with padding */}
          <div className="flex-1 overflow-y-auto py-1">
            {files.length === 0 ? (
              <p className="text-xs text-[var(--text-muted)] py-4 text-center">No files uploaded yet</p>
            ) : (
              files.map((f) => (
                <div key={f.id}
                  onClick={() => openDocument({ docId: f.id, fileName: f.name })}
                  className="flex items-center gap-2 cursor-pointer hover:bg-[rgba(255,255,255,0.04)] px-1 py-1 rounded transition-colors group">
                  <FileIcon fileType={f.file_type} />
                  <span className="text-[11px] truncate text-[var(--text-muted)] group-hover:text-[var(--text-secondary)] transition-colors flex-1">{f.name}</span>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* Bottom buttons */}
      <div className="px-3 py-2.5 border-t border-[var(--border)] shrink-0 space-y-1.5">
        <button onClick={handleFileUpload} disabled={isUploading}
          className="w-full bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white font-semibold py-2.5 rounded-lg flex items-center justify-center gap-2 transition-colors text-xs disabled:opacity-50">
          <svg aria-hidden="true" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M12 16V4m0 0L8 8m4-4l4 4" /><path d="M4 18h16" /></svg>
          {isUploading ? 'Uploading...' : 'Add Files'}
        </button>
        {files.length > 0 && (
          <a href={getExportUrl()} download
            aria-label="Export file list as CSV"
            className="w-full bg-[rgba(255,255,255,0.06)] hover:bg-[rgba(255,255,255,0.1)] text-[var(--text-secondary)] hover:text-white border border-[var(--border)] py-2 rounded-lg flex items-center justify-center gap-2 transition-colors text-xs block">
            <svg aria-hidden="true" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
            Export
          </a>
        )}
        <input ref={fileInputRef} type="file" accept={ACCEPTED} multiple onChange={onFilesSelected} className="hidden" aria-label="Upload documents" />
      </div>
    </aside>
    </>
  );
}
