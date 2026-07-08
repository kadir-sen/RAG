import type { ArtifactLinkBlock } from '../../../types/api';
import { downloadArtifact } from '../../../api/fileApi';

export default function ArtifactBlock({ block }: { block: ArtifactLinkBlock }) {
  return (
    <div className="my-1">
      <button
        onClick={() => void downloadArtifact(block.url, block.filename)}
        className="px-3 py-1.5 text-[11px] rounded-md border border-[var(--border)] hover:bg-[var(--bg-hover)] hover:border-[var(--accent)]/50 transition-colors text-[var(--text-secondary)]"
      >
        ⤓ {block.filename}
      </button>
    </div>
  );
}
