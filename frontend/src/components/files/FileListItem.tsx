import { memo } from 'react';
import type { FileInfo, NoticeMetadata } from '../../types/api';
import Badge from '../shared/Badge';

interface Props {
  file: FileInfo;
  onClick: () => void;
  noticeMetadata?: NoticeMetadata | null;
}

const typeIcon: Record<string, string> = {
  document: '\u{1F4C4}',
  email: '\u{1F4E7}',
  data: '\u{1F4CA}',
};

function FileListItem({ file, onClick, noticeMetadata }: Props) {
  const icon = typeIcon[file.file_type] || '\u{1F4C1}';
  const chips: string[] = [];
  if (file.ocr_pages > 0) chips.push(`${file.ocr_pages} OCR`);
  if (file.tables > 0) chips.push(`${file.tables} tbl`);
  if (file.rows > 0) chips.push(`${file.rows} rows`);
  if (file.notice_extracted) chips.push('notice');

  return (
    <button
      onClick={onClick}
      className="w-full flex flex-col px-3 py-2 rounded-lg hover:bg-[var(--bg-hover)] transition-colors text-left"
    >
      <div className="flex items-center gap-2">
        <span className="text-xs flex-shrink-0">{icon}</span>
        <span className="flex-1 text-xs text-[var(--text-primary)] truncate">
          {file.name}
        </span>
        {file.file_type === 'data' && file.data_table_status && (
          <span
            title={
              file.data_table_status === 'registered'
                ? `Queryable as SQL (${file.data_tables_count ?? 0} table(s))`
                : file.data_table_status === 'no_schema_match'
                  ? 'Indexed for RAG only — no schema match for SQL'
                  : 'Failed to register as SQL table'
            }
            className={
              'text-[9px] px-1.5 py-0.5 rounded font-semibold uppercase tracking-wide ' +
              (file.data_table_status === 'registered'
                ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                : file.data_table_status === 'no_schema_match'
                  ? 'bg-zinc-500/20 text-zinc-300 border border-zinc-500/30'
                  : 'bg-red-500/20 text-red-300 border border-red-500/30')
            }
          >
            {file.data_table_status === 'registered'
              ? 'DB'
              : file.data_table_status === 'no_schema_match'
                ? 'RAG'
                : 'ERR'}
          </span>
        )}
        <Badge label={file.file_type} />
      </div>
      {/* Metadata chips */}
      {chips.length > 0 && (
        <div className="flex gap-1.5 mt-1 ml-5">
          {chips.map((chip) => (
            <span
              key={chip}
              className="text-[9px] px-1.5 py-0.5 rounded bg-[var(--accent-glow)] text-[var(--accent)] font-medium"
            >
              {chip}
            </span>
          ))}
        </div>
      )}
      {/* Notice metadata */}
      {noticeMetadata && (noticeMetadata.sender || noticeMetadata.date) && (
        <p className="text-[10px] text-[var(--text-muted)] mt-0.5 ml-5 truncate">
          {[
            noticeMetadata.date,
            noticeMetadata.sender && `From: ${noticeMetadata.sender}`,
            noticeMetadata.recipient && `To: ${noticeMetadata.recipient}`,
          ].filter(Boolean).join(' \u00b7 ')}
        </p>
      )}
    </button>
  );
}

export default memo(FileListItem);
