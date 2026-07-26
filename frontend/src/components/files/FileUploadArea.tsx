import { useRef, useState, type DragEvent } from 'react';

const ACCEPTED =
  '.pdf,.docx,.doc,.txt,.xlsx,.xls,.csv,.eml,.msg';

interface Props {
  onUpload: (files: File[]) => void;
  isUploading?: boolean;
}

export default function FileUploadArea({ onUpload, isUploading }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length) onUpload(files);
  };

  const handleChange = () => {
    const files = Array.from(inputRef.current?.files ?? []);
    if (files.length) onUpload(files);
    if (inputRef.current) inputRef.current.value = '';
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      className={`mx-3 mb-2 p-3 rounded-lg border border-dashed cursor-pointer transition-colors text-center ${
        dragOver
          ? 'border-[var(--accent)] bg-[var(--accent)]/10'
          : 'border-[var(--border)] hover:border-[var(--accent)]'
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED}
        multiple
        onChange={handleChange}
        className="hidden"
      />
      <p className="text-xs text-[var(--text-secondary)]">
        {isUploading ? 'Uploading...' : 'Drop files or click to upload'}
      </p>
    </div>
  );
}
