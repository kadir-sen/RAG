import { useRef, useState, type DragEvent } from 'react';

const ACCEPTED =
  '.pdf,.docx,.doc,.txt,.xlsx,.xls,.csv,.eml,.msg';

interface Props {
  onUpload: (files: File[]) => void;
  isUploading?: boolean;
  storageUsedBytes?: number;
  storageLimitBytes?: number;
}

function formatStorage(bytes: number) {
  return `${(Math.max(0, bytes) / 1_000_000_000).toFixed(2)} GB`;
}

export default function FileUploadArea({
  onUpload,
  isUploading,
  storageUsedBytes = 0,
  storageLimitBytes = 0,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [selectionError, setSelectionError] = useState('');
  const remaining = Math.max(0, storageLimitBytes - storageUsedBytes);
  const quotaEnabled = storageLimitBytes > 0;
  const quotaFull = quotaEnabled && remaining <= 0;
  const quotaPercent = quotaEnabled ? (storageUsedBytes * 100) / storageLimitBytes : 0;

  const submitFiles = (files: File[]) => {
    if (!files.length || isUploading) return;
    const selectedBytes = files.reduce((total, file) => total + file.size, 0);
    if (quotaEnabled && selectedBytes > remaining) {
      setSelectionError(
        `These files need ${formatStorage(selectedBytes)}, but only ${formatStorage(remaining)} remains of your ${formatStorage(storageLimitBytes)} source-file allowance.`,
      );
      return;
    }
    setSelectionError('');
    onUpload(files);
  };

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files);
    submitFiles(files);
  };

  const handleChange = () => {
    const files = Array.from(inputRef.current?.files ?? []);
    submitFiles(files);
    if (inputRef.current) inputRef.current.value = '';
  };

  return (
    <div className="mx-1 mb-2 sm:mx-3">
      <div
        role="button"
        tabIndex={quotaFull || isUploading ? -1 : 0}
        aria-disabled={quotaFull || isUploading}
        aria-describedby={quotaEnabled ? 'upload-storage-status' : undefined}
        onKeyDown={(event) => {
          if ((event.key === 'Enter' || event.key === ' ') && !quotaFull && !isUploading) {
            event.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!quotaFull && !isUploading) setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => { if (!quotaFull && !isUploading) inputRef.current?.click(); }}
        className={`flex min-h-16 items-center justify-center rounded-lg border border-dashed p-3 text-center transition-colors ${
          quotaFull || isUploading
            ? 'cursor-not-allowed border-[var(--border)] opacity-60'
            : dragOver
              ? 'cursor-pointer border-[var(--accent)] bg-[var(--accent)]/10'
              : 'cursor-pointer border-[var(--border)] hover:border-[var(--accent)]'
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED}
          multiple
          disabled={quotaFull || isUploading}
          onChange={handleChange}
          className="hidden"
        />
        <div>
          <p className="text-xs text-[var(--text-secondary)]">
            {isUploading ? 'Uploading…' : quotaFull ? '30 GB source-file limit reached' : 'Drop files or click to upload'}
          </p>
          {quotaEnabled && (
            <p id="upload-storage-status" className="mt-1 font-mono text-[9px] text-[var(--text-muted)]">
              {formatStorage(storageUsedBytes)} used · {formatStorage(remaining)} remaining · {formatStorage(storageLimitBytes)} limit
            </p>
          )}
          <p className="mt-1 text-[9px] text-[var(--text-muted)]">
            OCR, metadata and indexing run automatically after upload.
          </p>
        </div>
      </div>
      {(selectionError || quotaPercent >= 90) && (
        <p role={selectionError || quotaFull ? 'alert' : 'status'} className={`mt-2 text-[10px] ${selectionError || quotaFull ? 'text-[var(--danger)]' : 'text-[var(--amber)]'}`}>
          {selectionError || `${quotaPercent.toFixed(1)}% of the 30 GB source-file allowance is in use.`}
        </p>
      )}
    </div>
  );
}
