import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useUIStore } from '../../stores/uiStore';
import { useChatStore } from '../../stores/chatStore';
import { useFiles } from '../../hooks/useFiles';
import { useConversationDocs } from '../../hooks/useConversationDocs';
import { getIndexingStatus, getStats, getExportUrl } from '../../api/fileApi';
import FileUploadArea from './FileUploadArea';
import FileListItem from './FileListItem';
import LibraryPickerModal from './LibraryPickerModal';
import KnowledgeModal from '../knowledge/KnowledgeModal';
import Badge from '../shared/Badge';
import DataTablesPanel from '../admin/DataTablesPanel';
import { getFileTypeBadge } from '../../styles/tokens';

export default function LeftDrawer() {
  const { leftDrawerOpen, toggleLeftDrawer, openDocument, leftDrawerTab, setLeftDrawerTab } = useUIStore();
  const activeConversationId = useChatStore(s => s.activeConversationId);
  const { files, uploadMultiple, isUploading, deleteFile } = useFiles();
  const { docs, addDocs, removeDoc } = useConversationDocs(activeConversationId);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [knowledgeOpen, setKnowledgeOpen] = useState(false);
  const [dataTablesOpen, setDataTablesOpen] = useState(false);
  const [openFolders, setOpenFolders] = useState<Record<'documents' | 'tables' | 'communications', boolean>>({
    documents: false,
    tables: false,
    communications: false,
  });
  const toggleFolder = (key: 'documents' | 'tables' | 'communications') =>
    setOpenFolders((prev) => ({ ...prev, [key]: !prev[key] }));

  const indexing = useQuery({
    queryKey: ['indexingStatus'],
    queryFn: getIndexingStatus,
    refetchInterval: leftDrawerTab === 'library' ? 5000 : false,
    enabled: leftDrawerTab === 'library',
  });

  const stats = useQuery({
    queryKey: ['dashboardStats'],
    queryFn: getStats,
    staleTime: 30_000,
  });

  const handleUpload = (fileList: File[]) => {
    if (fileList.length) uploadMultiple(fileList);
  };

  const handleAddFromLibrary = (docIds: string[]) => {
    if (docIds.length > 0) {
      addDocs.mutate(docIds);
    }
  };

  if (!leftDrawerOpen) {
    return (
      <div className="w-11 flex flex-col items-center py-3 border-r border-[var(--border)] bg-[var(--bg-secondary)]">
        <button
          onClick={toggleLeftDrawer}
          className="p-2 rounded-lg hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
          title="Open documents panel"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <path d="M2 3h12M2 7h12M2 11h12" />
          </svg>
        </button>
      </div>
    );
  }

  const existingDocIds = docs.map(d => d.doc_id);
  const vecCount = stats.data?.vectors ?? 0;
  const tblCount = stats.data?.tables ?? 0;

  return (
    <div className="w-64 flex flex-col border-r border-[var(--border)] bg-[var(--bg-secondary)]">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-[var(--border)]">
        <div className="flex items-center gap-2">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round">
            <path d="M1.5 4.5l5-3 5 3v6l-5 3-5-3z" />
            <path d="M1.5 4.5L6.5 7.5M6.5 7.5v6M6.5 7.5l5-3" />
          </svg>
          <span className="text-sm font-medium text-[var(--text-primary)]">
            Documents
          </span>
        </div>
        <button
          onClick={toggleLeftDrawer}
          className="p-1 rounded-md hover:bg-[var(--bg-hover)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <line x1="3" y1="3" x2="9" y2="9" />
            <line x1="9" y1="3" x2="3" y2="9" />
          </svg>
        </button>
      </div>

      {/* Tab bar */}
      <div className="flex border-b border-[var(--border)]">
        <button
          onClick={() => setLeftDrawerTab('documents')}
          className={`flex-1 py-2 text-xs font-medium transition-colors ${
            leftDrawerTab === 'documents'
              ? 'text-[var(--accent)] border-b-2 border-[var(--accent)]'
              : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
          }`}
        >
          Documents
        </button>
        <button
          onClick={() => setLeftDrawerTab('library')}
          className={`flex-1 py-2 text-xs font-medium transition-colors ${
            leftDrawerTab === 'library'
              ? 'text-[var(--accent)] border-b-2 border-[var(--accent)]'
              : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
          }`}
        >
          Library
          {files.length > 0 && (
            <span className="ml-1 text-[var(--text-muted)]">({files.length})</span>
          )}
        </button>
      </div>

      {/* Tab content */}
      {leftDrawerTab === 'documents' ? (
        <>
          {/* Conversation documents */}
          <div className="flex-1 overflow-y-auto px-2 py-1">
            {docs.length === 0 ? (
              <div className="px-2 py-8 text-center text-xs text-[var(--text-muted)]">
                No documents added yet.
              </div>
            ) : (
              docs.map(doc => (
                <div
                  key={doc.doc_id}
                  className="group flex items-center rounded-lg hover:bg-[var(--bg-hover)] transition-colors mb-0.5"
                >
                  <div
                    className="w-0.5 h-6 rounded-full ml-1 flex-shrink-0"
                    style={{ background: getFileTypeBadge(doc.file_type).dot }}
                  />
                  <div
                    className="flex-1 min-w-0 cursor-pointer"
                    onClick={() => openDocument({ docId: doc.doc_id, fileName: doc.file_name })}
                  >
                    <FileListItem
                      file={{
                        id: doc.doc_id,
                        name: doc.file_name,
                        file_type: doc.file_type,
                        pages: null,
                        ocr_pages: 0,
                        tables: doc.table_names.length,
                        rows: 0,
                        notice_extracted: doc.notice_extracted,
                      }}
                      onClick={() => {}}
                      noticeMetadata={doc.notice_metadata}
                    />
                  </div>
                  <button
                    onClick={() => removeDoc.mutate(doc.doc_id)}
                    className="hidden group-hover:flex items-center justify-center w-6 h-6 mr-1 rounded-md text-[var(--text-muted)] hover:text-[var(--danger)] hover:bg-[var(--bg-surface)] transition-colors"
                    title="Remove from conversation"
                  >
                    <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                      <line x1="2" y1="2" x2="8" y2="8" />
                      <line x1="8" y1="2" x2="2" y2="8" />
                    </svg>
                  </button>
                </div>
              ))
            )}
          </div>

          {/* Add documents / Collections buttons */}
          <div className="px-3 py-2 border-t border-[var(--border)] space-y-1.5">
            <button
              onClick={() => setPickerOpen(true)}
              className="w-full py-2 text-xs font-medium text-[var(--accent)] glass rounded-lg hover:bg-[var(--accent-glow)] hover:border-[var(--accent)] transition-all"
            >
              + Add Documents
            </button>
            <button
              onClick={() => setKnowledgeOpen(true)}
              className="w-full py-1.5 text-[11px] font-medium text-[var(--text-secondary)] hover:text-white border border-[var(--border)] rounded-lg hover:bg-[var(--bg-hover)] transition-all flex items-center justify-center gap-1.5"
              title="Manage knowledge collections"
            >
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z" />
                <path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z" />
              </svg>
              Knowledge Collections
            </button>
          </div>

          {/* Stats */}
          <div className="px-3 py-1.5 text-[10px] text-[var(--text-muted)]">
            {docs.length} document{docs.length !== 1 ? 's' : ''} in conversation
          </div>
        </>
      ) : (
        <>
          {/* Upload area */}
          <FileUploadArea onUpload={handleUpload} isUploading={isUploading} />

          {/* Stats metrics */}
          <div className="flex gap-2 px-3 py-2">
            <div className="flex-1 rounded-lg bg-[var(--bg-primary)] p-2.5 text-center border border-[var(--border)]">
              <p className="text-lg font-bold text-[var(--accent)]">{vecCount}</p>
              <p className="text-[10px] text-[var(--text-muted)] font-medium">Vectors</p>
            </div>
            <button
              onClick={() => setDataTablesOpen(true)}
              className="flex-1 rounded-lg bg-[var(--bg-primary)] p-2.5 text-center border border-[var(--border)] hover:border-[var(--accent)]/50 transition-colors"
              title="Manage SQL data tables"
            >
              <p className="text-lg font-bold text-[var(--accent)]">{tblCount}</p>
              <p className="text-[10px] text-[var(--text-muted)] font-medium">
                Tables
                <span className="ml-1 underline opacity-70">manage</span>
              </p>
            </button>
          </div>

          {/* Indexing status */}
          {indexing.data && indexing.data.length > 0 && (
            <div className="px-3 mb-2">
              <h3 className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-1.5">
                Indexing
              </h3>
              <div className="space-y-1">
                {indexing.data.map((s) => (
                  <div
                    key={s.file_id}
                    className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-[var(--bg-primary)]"
                  >
                    <span className="text-xs text-[var(--text-primary)] flex-1 truncate">
                      {s.filename}
                    </span>
                    <Badge label={s.status} />
                    {s.status === 'indexing' && (
                      <div className="w-16 h-1 bg-[var(--bg-surface)] rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full transition-all duration-500"
                          style={{
                            width: `${Math.round(s.progress * 100)}%`,
                            background: 'var(--gradient-accent)',
                          }}
                        />
                      </div>
                    )}
                    {s.error && (
                      <span className="text-[10px] text-[var(--danger)]" title={s.error}>!</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Export bar */}
          {files.length > 0 && (
            <div className="flex items-center justify-between px-3 pb-1">
              <h3 className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                Library ({files.length})
              </h3>
              <a
                href={getExportUrl()}
                download
                className="text-[10px] text-[var(--accent)] hover:underline cursor-pointer"
                title="Download file list as Excel"
              >
                Export
              </a>
            </div>
          )}

          {/* Folder list */}
          <div className="flex-1 overflow-y-auto px-2 py-1">
            {(() => {
              const groups = {
                documents: files.filter((f) => {
                  const t = (f.file_type || '').toLowerCase();
                  return t === 'document' || t === 'pdf' || t === 'doc' || t === 'docx' || t === 'text' || t === 'txt';
                }),
                tables: files.filter((f) => {
                  const t = (f.file_type || '').toLowerCase();
                  return t === 'data' || t === 'excel' || t === 'xls' || t === 'xlsx' || t === 'csv';
                }),
                communications: files.filter((f) => {
                  const t = (f.file_type || '').toLowerCase();
                  return t === 'email' || t === 'eml' || t === 'msg';
                }),
              };

              const FolderIcon = ({ open }: { open: boolean }) => (
                <svg
                  width="12"
                  height="12"
                  viewBox="0 0 12 12"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className={`transition-transform ${open ? 'rotate-90' : ''}`}
                >
                  <path d="M4 2.5L7.5 6L4 9.5" />
                </svg>
              );

              const folders: Array<{
                key: 'documents' | 'tables' | 'communications';
                label: string;
                items: typeof files;
                accent: string;
              }> = [
                { key: 'documents', label: 'Documents', items: groups.documents, accent: 'var(--type-pdf)' },
                { key: 'tables', label: 'Tables', items: groups.tables, accent: 'var(--type-xls)' },
                { key: 'communications', label: 'Communications', items: groups.communications, accent: 'var(--type-eml)' },
              ];

              if (files.length === 0) {
                return (
                  <div className="px-2 py-8 text-center text-xs text-[var(--text-muted)]">
                    No files uploaded yet.
                  </div>
                );
              }

              return folders.map((folder) => {
                const isOpen = openFolders[folder.key];
                return (
                  <div key={folder.key} className="mb-1">
                    <button
                      onClick={() => toggleFolder(folder.key)}
                      className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-[var(--bg-hover)] transition-colors text-left"
                    >
                      <FolderIcon open={isOpen} />
                      <span
                        className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                        style={{ background: folder.accent }}
                      />
                      <span className="text-xs font-medium text-[var(--text-primary)] flex-1">
                        {folder.label}
                      </span>
                      <span className="text-[10px] text-[var(--text-muted)]">
                        {folder.items.length}
                      </span>
                    </button>

                    {isOpen && (
                      <div className="ml-3 mt-0.5 border-l border-[var(--border)] pl-1">
                        {folder.items.length === 0 ? (
                          <div className="px-2 py-2 text-[11px] text-[var(--text-muted)] italic">
                            Empty
                          </div>
                        ) : (
                          folder.items.map((f) => (
                            <div
                              key={f.id}
                              className="group flex items-center rounded-lg hover:bg-[var(--bg-hover)] transition-colors mb-0.5"
                            >
                              <div
                                className="w-0.5 h-6 rounded-full ml-1 flex-shrink-0"
                                style={{ background: getFileTypeBadge(f.file_type).dot }}
                              />
                              <div
                                className="flex-1 min-w-0 cursor-pointer"
                                onClick={() => openDocument({ docId: f.id, fileName: f.name })}
                              >
                                <FileListItem file={f} onClick={() => {}} />
                              </div>
                              <button
                                onClick={() => deleteFile(f.id)}
                                className="hidden group-hover:flex items-center justify-center w-6 h-6 mr-1 rounded-md text-[var(--text-muted)] hover:text-[var(--danger)] hover:bg-[var(--bg-surface)] transition-colors"
                                title="Remove file"
                              >
                                <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                                  <line x1="2" y1="2" x2="8" y2="8" />
                                  <line x1="8" y1="2" x2="2" y2="8" />
                                </svg>
                              </button>
                            </div>
                          ))
                        )}
                      </div>
                    )}
                  </div>
                );
              });
            })()}
          </div>
        </>
      )}

      {/* Library picker modal */}
      <LibraryPickerModal
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        existingDocIds={existingDocIds}
        onAdd={handleAddFromLibrary}
      />

      {/* Knowledge collections modal */}
      <KnowledgeModal
        open={knowledgeOpen}
        onClose={() => setKnowledgeOpen(false)}
        onApplyToChat={(docIds) => {
          if (docIds.length > 0) addDocs.mutate(docIds);
        }}
        applyDisabled={!activeConversationId}
      />

      {/* SQL data tables admin panel */}
      <DataTablesPanel
        open={dataTablesOpen}
        onClose={() => setDataTablesOpen(false)}
      />
    </div>
  );
}
