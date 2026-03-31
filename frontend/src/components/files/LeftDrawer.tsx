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
import Badge from '../shared/Badge';

const typeColor: Record<string, string> = {
  document: '#3b82f6',
  data: '#10b981',
  email: '#f59e0b',
};

export default function LeftDrawer() {
  const { leftDrawerOpen, toggleLeftDrawer, openDocument, leftDrawerTab, setLeftDrawerTab } = useUIStore();
  const activeConversationId = useChatStore(s => s.activeConversationId);
  const { files, uploadMultiple, isUploading, deleteFile } = useFiles();
  const { docs, addDocs, removeDoc } = useConversationDocs(activeConversationId);
  const [pickerOpen, setPickerOpen] = useState(false);

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
                    style={{ background: typeColor[doc.file_type] || '#6366f1' }}
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

          {/* Add documents button */}
          <div className="px-3 py-2 border-t border-[var(--border)]">
            <button
              onClick={() => setPickerOpen(true)}
              className="w-full py-2 text-xs font-medium text-[var(--accent)] glass rounded-lg hover:bg-[var(--accent-glow)] hover:border-[var(--accent)] transition-all"
            >
              + Add Documents
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
            <div className="flex-1 rounded-lg bg-[var(--bg-primary)] p-2.5 text-center border border-[var(--border)]">
              <p className="text-lg font-bold text-[var(--accent)]">{tblCount}</p>
              <p className="text-[10px] text-[var(--text-muted)] font-medium">Tables</p>
            </div>
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

          {/* File list header */}
          {files.length > 0 && (
            <div className="flex items-center justify-between px-3 pb-1">
              <h3 className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                Uploaded Files ({files.length})
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

          {/* File list */}
          <div className="flex-1 overflow-y-auto px-2 py-1">
            {files.length === 0 ? (
              <div className="px-2 py-8 text-center text-xs text-[var(--text-muted)]">
                No files uploaded yet.
              </div>
            ) : (
              files.map((f) => (
                <div
                  key={f.id}
                  className="group flex items-center rounded-lg hover:bg-[var(--bg-hover)] transition-colors mb-0.5"
                >
                  <div
                    className="w-0.5 h-6 rounded-full ml-1 flex-shrink-0"
                    style={{ background: typeColor[f.file_type] || '#6366f1' }}
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
        </>
      )}

      {/* Library picker modal */}
      <LibraryPickerModal
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        existingDocIds={existingDocIds}
        onAdd={handleAddFromLibrary}
      />
    </div>
  );
}
