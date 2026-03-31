import type { FileInfo } from '../../types/api';
import type { ViewerDoc } from '../../stores/uiStore';
import FileListItem from './FileListItem';

interface Props {
  files: FileInfo[];
  onFileClick: (doc: ViewerDoc) => void;
}

export default function FileList({ files, onFileClick }: Props) {
  if (!files.length) {
    return (
      <p className="px-3 py-4 text-xs text-[var(--text-secondary)]">
        No files uploaded yet.
      </p>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto py-1">
      {files.map((f) => (
        <FileListItem
          key={f.id}
          file={f}
          onClick={() =>
            onFileClick({ docId: f.id, fileName: f.name })
          }
        />
      ))}
    </div>
  );
}
