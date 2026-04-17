import { useState, useEffect, useRef } from 'react';
import {
  useKnowledgeCollections,
  useKnowledgeCollection,
} from '../../hooks/useKnowledge';
import LibraryPickerModal from '../files/LibraryPickerModal';
import Badge from '../shared/Badge';
import type { KnowledgeCollection } from '../../types/api';

interface Props {
  open: boolean;
  onClose: () => void;
  onApplyToChat?: (docIds: string[]) => void;
  applyDisabled?: boolean;
}

export default function KnowledgeModal({
  open,
  onClose,
  onApplyToChat,
  applyDisabled = false,
}: Props) {
  const {
    collections,
    isLoading,
    createCollection,
    updateCollection,
    deleteCollection,
    addDocuments,
    removeDocument,
  } = useKnowledgeCollections();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  const detail = useKnowledgeCollection(selectedId);

  useEffect(() => {
    if (open) {
      setSelectedId(null);
      setCreating(false);
      setEditingId(null);
      setPendingDeleteId(null);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const handleCreate = async () => {
    const name = newName.trim();
    if (!name) return;
    const col = await createCollection({ name, description: newDesc.trim() });
    setNewName('');
    setNewDesc('');
    setCreating(false);
    setSelectedId(col.collection_id);
  };

  const handleRenameCommit = async (id: string) => {
    const name = editName.trim();
    if (name) {
      await updateCollection({ id, name });
    }
    setEditingId(null);
  };

  const handleDelete = (id: string) => {
    deleteCollection(id);
    if (selectedId === id) setSelectedId(null);
    setPendingDeleteId(null);
  };

  const handleAddDocs = async (docIds: string[]) => {
    if (!selectedId || docIds.length === 0) return;
    await addDocuments({ id: selectedId, docIds });
  };

  const existingDocIds = detail.data?.document_ids ?? [];

  return (
    <>
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
        onClick={onClose}
      >
        <div
          ref={dialogRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby="knowledge-modal-title"
          className="bg-[var(--bg-secondary)] rounded-lg border border-[var(--border)] w-full max-w-3xl h-[80vh] flex flex-col"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="px-4 py-3 border-b border-[var(--border)] flex items-center justify-between">
            <div>
              <h3 id="knowledge-modal-title" className="text-[var(--text-primary)] font-medium">
                Knowledge Koleksiyonları
              </h3>
              <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
                Dokümanları gruplara ayırın, sohbete tek tıkla ekleyin
              </p>
            </div>
            <button
              onClick={onClose}
              className="text-[var(--text-muted)] hover:text-[var(--text-primary)] text-lg"
              aria-label="Kapat"
            >
              &times;
            </button>
          </div>

          <div className="flex flex-1 overflow-hidden">
            {/* Sol: koleksiyon listesi */}
            <div className="w-1/3 border-r border-[var(--border)] flex flex-col">
              <div className="p-3 border-b border-[var(--border)]">
                {creating ? (
                  <div className="space-y-2">
                    <input
                      value={newName}
                      onChange={(e) => setNewName(e.target.value)}
                      placeholder="Koleksiyon adı"
                      autoFocus
                      className="w-full bg-[var(--bg-primary)] border border-[var(--border)] rounded-md px-2 py-1.5 text-xs text-white focus:outline-none focus:border-[var(--accent)]"
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleCreate();
                        if (e.key === 'Escape') setCreating(false);
                      }}
                    />
                    <input
                      value={newDesc}
                      onChange={(e) => setNewDesc(e.target.value)}
                      placeholder="Açıklama (opsiyonel)"
                      className="w-full bg-[var(--bg-primary)] border border-[var(--border)] rounded-md px-2 py-1.5 text-xs text-white focus:outline-none focus:border-[var(--accent)]"
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleCreate();
                        if (e.key === 'Escape') setCreating(false);
                      }}
                    />
                    <div className="flex gap-1.5">
                      <button
                        onClick={handleCreate}
                        disabled={!newName.trim()}
                        className="flex-1 text-[11px] px-2 py-1 bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white rounded disabled:opacity-40"
                      >
                        Oluştur
                      </button>
                      <button
                        onClick={() => setCreating(false)}
                        className="text-[11px] px-2 py-1 text-[var(--text-muted)] hover:text-white"
                      >
                        İptal
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={() => setCreating(true)}
                    className="w-full text-xs font-medium text-[var(--accent)] glass rounded-md py-1.5 hover:bg-[var(--accent-glow)] hover:border-[var(--accent)] transition-all"
                  >
                    + Yeni Koleksiyon
                  </button>
                )}
              </div>

              <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
                {isLoading ? (
                  <p className="text-xs text-[var(--text-muted)] p-3 text-center">
                    Yükleniyor...
                  </p>
                ) : collections.length === 0 ? (
                  <p className="text-xs text-[var(--text-muted)] p-3 text-center">
                    Henüz koleksiyon yok
                  </p>
                ) : (
                  collections.map((c: KnowledgeCollection) => {
                    const isActive = c.collection_id === selectedId;
                    const isEditing = c.collection_id === editingId;
                    const isPending = c.collection_id === pendingDeleteId;
                    return (
                      <div
                        key={c.collection_id}
                        className={`group flex items-center gap-1 px-2 py-1.5 rounded-md cursor-pointer text-xs transition-colors ${
                          isActive
                            ? 'bg-[var(--bg-hover)] text-white'
                            : 'text-[var(--text-secondary)] hover:bg-[rgba(255,255,255,0.04)] hover:text-white'
                        }`}
                        onClick={() => {
                          if (!isEditing && !isPending) setSelectedId(c.collection_id);
                        }}
                      >
                        {isEditing ? (
                          <input
                            autoFocus
                            value={editName}
                            onChange={(e) => setEditName(e.target.value)}
                            onBlur={() => handleRenameCommit(c.collection_id)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') handleRenameCommit(c.collection_id);
                              if (e.key === 'Escape') setEditingId(null);
                            }}
                            onClick={(e) => e.stopPropagation()}
                            className="flex-1 bg-transparent text-xs text-white outline-none border-b border-[var(--accent)]"
                          />
                        ) : isPending ? (
                          <div className="flex items-center gap-1 flex-1">
                            <span className="text-[10px] text-[var(--danger)]">Sil?</span>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleDelete(c.collection_id);
                              }}
                              className="text-[9px] px-1.5 py-0.5 bg-[var(--danger)] text-white rounded"
                            >
                              Evet
                            </button>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                setPendingDeleteId(null);
                              }}
                              className="text-[9px] px-1.5 py-0.5 text-[var(--text-muted)]"
                            >
                              Hayır
                            </button>
                          </div>
                        ) : (
                          <>
                            <div className="flex-1 min-w-0">
                              <p className="truncate">{c.name}</p>
                              <p className="text-[9px] text-[var(--text-muted)]">
                                {c.document_count} doküman
                              </p>
                            </div>
                            <div className="opacity-0 group-hover:opacity-100 flex items-center gap-0.5">
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setEditingId(c.collection_id);
                                  setEditName(c.name);
                                }}
                                className="p-0.5 text-[var(--text-muted)] hover:text-white"
                                title="Yeniden adlandır"
                              >
                                <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                                  <path d="M7 2l3 3-6 6H1V8z" />
                                </svg>
                              </button>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setPendingDeleteId(c.collection_id);
                                }}
                                className="p-0.5 text-[var(--text-muted)] hover:text-[var(--danger)]"
                                title="Sil"
                              >
                                <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                                  <path d="M2 3h8M4 3V2h4v1M5 5v4M7 5v4M3 3l.5 7h5l.5-7" />
                                </svg>
                              </button>
                            </div>
                          </>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            </div>

            {/* Sağ: koleksiyon detayı */}
            <div className="flex-1 flex flex-col overflow-hidden">
              {!selectedId ? (
                <div className="flex-1 flex items-center justify-center text-xs text-[var(--text-muted)] p-6 text-center">
                  Soldan bir koleksiyon seçin veya yeni bir koleksiyon oluşturun.
                </div>
              ) : (
                <>
                  <div className="px-4 py-3 border-b border-[var(--border)] flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <h4 className="text-sm text-[var(--text-primary)] font-medium truncate">
                        {detail.data?.name ?? '...'}
                      </h4>
                      {detail.data?.description && (
                        <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
                          {detail.data.description}
                        </p>
                      )}
                    </div>
                    <button
                      onClick={() => {
                        if (onApplyToChat && detail.data) {
                          onApplyToChat(detail.data.document_ids);
                          onClose();
                        }
                      }}
                      disabled={
                        applyDisabled ||
                        !onApplyToChat ||
                        !detail.data ||
                        detail.data.document_ids.length === 0
                      }
                      className="shrink-0 text-[11px] px-3 py-1.5 bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white rounded disabled:opacity-40"
                      title="Bu koleksiyonun dokümanlarını aktif sohbete ekle"
                    >
                      Sohbete Uygula
                    </button>
                  </div>

                  <div className="flex-1 overflow-y-auto p-3">
                    {detail.isLoading ? (
                      <p className="text-xs text-[var(--text-muted)] text-center py-6">
                        Yükleniyor...
                      </p>
                    ) : (detail.data?.documents ?? []).length === 0 ? (
                      <p className="text-xs text-[var(--text-muted)] text-center py-6">
                        Bu koleksiyonda henüz doküman yok.
                      </p>
                    ) : (
                      (detail.data?.documents ?? []).map((d) => (
                        <div
                          key={d.doc_id}
                          className="group flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-[var(--bg-hover)] transition-colors"
                        >
                          <Badge
                            label={
                              d.extension.includes('pdf')
                                ? 'PDF'
                                : d.extension.includes('xls') || d.extension.includes('csv')
                                  ? 'Excel'
                                  : d.extension.includes('eml') || d.extension.includes('msg')
                                    ? 'Email'
                                    : 'Doc'
                            }
                          />
                          <p className="flex-1 min-w-0 text-xs text-[var(--text-primary)] truncate">
                            {d.file_name}
                          </p>
                          <button
                            onClick={() =>
                              selectedId && removeDocument({ id: selectedId, docId: d.doc_id })
                            }
                            className="opacity-0 group-hover:opacity-100 p-1 text-[var(--text-muted)] hover:text-[var(--danger)]"
                            title="Koleksiyondan çıkar"
                          >
                            <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                              <line x1="2" y1="2" x2="10" y2="10" />
                              <line x1="10" y1="2" x2="2" y2="10" />
                            </svg>
                          </button>
                        </div>
                      ))
                    )}
                  </div>

                  <div className="px-3 py-2 border-t border-[var(--border)]">
                    <button
                      onClick={() => setPickerOpen(true)}
                      className="w-full text-xs font-medium text-[var(--accent)] glass rounded-md py-1.5 hover:bg-[var(--accent-glow)] hover:border-[var(--accent)] transition-all"
                    >
                      + Doküman Ekle
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </div>

      <LibraryPickerModal
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        existingDocIds={existingDocIds}
        onAdd={handleAddDocs}
      />
    </>
  );
}
