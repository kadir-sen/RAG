import { useState, useEffect } from 'react';
import { useDocViewer } from '../../hooks/useDocViewer';
import ViewerToolbar from './ViewerToolbar';
import PdfViewer from './PdfViewer';
import TextViewer from './TextViewer';
import ExcelPreview from './ExcelPreview';
import Skeleton from '../shared/Skeleton';

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

  return (
    <div className="flex flex-col h-full border-l border-[var(--border)] bg-[var(--bg-primary)]">
      <ViewerToolbar
        fileName={doc.fileName}
        page={content?.page}
        totalPages={content?.total_pages}
        onPrev={handlePrev}
        onNext={handleNext}
        onClose={closeViewer}
        onExport={content?.type === 'table' && content.rows?.length ? () => {
          const rows = content.rows;
          if (!rows.length) return;
          const cols = content.columns?.length ? content.columns : Object.keys(rows[0]);
          const csv = [cols.join(','), ...rows.map((r: Record<string, unknown>) => cols.map(c => {
            const v = String(r[c] ?? '');
            return v.includes(',') ? `"${v}"` : v;
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

      {isLoadingContent ? (
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
