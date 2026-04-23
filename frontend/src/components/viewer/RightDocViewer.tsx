import { useState, useEffect } from 'react';
import { useDocViewer } from '../../hooks/useDocViewer';
import ViewerToolbar from './ViewerToolbar';
import PdfViewer from './PdfViewer';
import TextViewer from './TextViewer';
import ExcelPreview from './ExcelPreview';
import Skeleton from '../shared/Skeleton';

type TypeKey = 'excel' | 'pdf' | 'email' | 'text';

const TYPE_STYLES: Record<TypeKey, { label: string; band: string; bgClass: string; textClass: string; dotClass: string; tint: string }> = {
  excel: { label: 'XLS',  band: 'bg-green-500',  bgClass: 'bg-green-500/15',  textClass: 'text-green-400',  dotClass: 'bg-green-500',  tint: 'bg-[rgba(16,185,129,0.02)]' },
  pdf:   { label: 'PDF',  band: 'bg-red-500',    bgClass: 'bg-red-500/15',    textClass: 'text-red-400',    dotClass: 'bg-red-500',    tint: '' },
  email: { label: 'MAIL', band: 'bg-blue-500',   bgClass: 'bg-blue-500/15',   textClass: 'text-blue-400',   dotClass: 'bg-blue-500',   tint: '' },
  text:  { label: 'DOC',  band: 'bg-gray-400',   bgClass: 'bg-gray-500/15',   textClass: 'text-gray-300',   dotClass: 'bg-gray-400',   tint: '' },
};

function resolveTypeKey(fileName: string, contentType?: string): TypeKey {
  if (contentType === 'table') return 'excel';
  if (contentType === 'pdf') return 'pdf';
  const ext = fileName.toLowerCase().match(/\.([a-z0-9]+)$/)?.[1] ?? '';
  if (['xlsx', 'xls', 'csv'].includes(ext)) return 'excel';
  if (ext === 'pdf') return 'pdf';
  if (['eml', 'msg'].includes(ext)) return 'email';
  return 'text';
}

export default function RightDocViewer() {
  const { isOpen, doc, content, isLoadingContent, closeViewer, openDocument } =
    useDocViewer();
  const [page, setPage] = useState(1);

  // Sync page state with anchor from citation chip clicks
  useEffect(() => {
    if (doc?.anchor) {
      const match = doc.anchor.match(/page_(\d+)/);
      if (match) setPage(parseInt(match[1], 10));
    } else {
      setPage(1);
    }
  }, [doc?.anchor, doc?.docId]);

  if (!isOpen || !doc) return null;

  const handlePrev = () => {
    if (page > 1) {
      const newPage = page - 1;
      setPage(newPage);
      openDocument({ ...doc, anchor: `page_${newPage}` });
    }
  };

  const handleNext = () => {
    if (content && page < content.total_pages) {
      const newPage = page + 1;
      setPage(newPage);
      openDocument({ ...doc, anchor: `page_${newPage}` });
    }
  };

  const typeKey = resolveTypeKey(doc.fileName, content?.type);
  const typeStyle = TYPE_STYLES[typeKey];

  return (
    <div className={`flex flex-col h-full border-l border-[var(--border)] bg-[var(--bg-secondary)] ${typeStyle.tint}`}>
      <div className={`h-[2px] shrink-0 ${typeStyle.band}`} aria-hidden="true" />
      <ViewerToolbar
        fileName={doc.fileName}
        page={content?.page}
        totalPages={content?.total_pages}
        onPrev={handlePrev}
        onNext={handleNext}
        onClose={closeViewer}
        typeBadge={{ label: typeStyle.label, dotClass: typeStyle.dotClass, bgClass: typeStyle.bgClass, textClass: typeStyle.textClass }}
        onExport={content?.type === 'table' && content.rows?.length ? () => {
          const rows = content.rows;
          if (!rows.length) return;
          const cols = content.columns?.length ? content.columns : Object.keys(rows[0]);
          const csv = [cols.join(','), ...rows.map((r: Record<string, unknown>) => cols.map(c => {
            const v = String(r[c] ?? '');
            const escaped = v.replace(/"/g, '""');
            return v.includes(',') || v.includes('"') || v.includes('\n') ? `"${escaped}"` : v;
          }).join(','))].join('\n');
          const blob = new Blob([csv], { type: 'text/csv' });
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = `${doc.fileName.replace(/\.[^.]+$/, '')}_export.csv`;
          a.click();
          URL.revokeObjectURL(url);
        } : undefined}
      />

      {!doc.docId || !doc.docId.trim() ? (
        <div className="p-4 text-sm text-[var(--text-muted)]">
          This document cannot be previewed — no document ID available.
        </div>
      ) : isLoadingContent ? (
        <div className="p-4 space-y-3">
          <Skeleton className="h-6 w-3/4" />
          <Skeleton className="h-64 w-full" />
          <Skeleton className="h-4 w-1/2" />
        </div>
      ) : content?.error ? (
        <div className="p-4 text-sm text-[var(--danger)]">{content.error}</div>
      ) : content?.type === 'pdf' ? (
        <PdfViewer content={content} highlightText={doc.highlightText} />
      ) : content?.type === 'table' ? (
        <ExcelPreview content={content} />
      ) : content ? (
        <TextViewer content={content} highlightText={doc.highlightText} />
      ) : null}
    </div>
  );
}
