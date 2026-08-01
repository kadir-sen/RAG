import { useQuery } from '@tanstack/react-query';
import { getLibrary } from '../../api/libraryApi';
import { useChatStore } from '../../stores/chatStore';
import { getFileTypeBadge } from '../../styles/tokens';
import type { LibraryDocument } from '../../types/api';
import { useProjectStore } from '../../stores/projectStore';

// Tiles for the files (documents + emails) the user picked in the sidebar.
// Rendered just above the chat input so the selected context is always visible;
// each tile is an image-like file chip with an × to deselect.
export default function SelectedContextBar() {
  const projectId = useProjectStore((state) => state.selectedProjectId);
  const { selectedIds, toggleSelection, clearSelection } = useChatStore();
  const libraryQuery = useQuery({ queryKey: ['library', projectId], queryFn: getLibrary, enabled: Boolean(projectId), staleTime: 60_000 });

  if (selectedIds.length === 0) return null;

  const byId = new Map<string, LibraryDocument>(
    (libraryQuery.data ?? []).map((d) => [d.doc_id, d]),
  );

  return (
    <div className="flex items-center gap-2 overflow-x-auto pb-2 pt-1">
      <span className="shrink-0 font-mono text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
        Context
      </span>
      {selectedIds.map((id) => {
        const doc = byId.get(id);
        const name = doc?.file_name || id;
        const badge = getFileTypeBadge(doc?.extension || doc?.file_type);
        return (
          <div
            key={id}
            className="shrink-0 flex items-center gap-2 pl-1.5 pr-1 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--bg-surface)]"
          >
            {/* image-like type tile */}
            <span
              className="grid place-items-center w-8 h-8 rounded border border-[var(--border)] bg-[var(--wash)] font-mono text-[8px] font-semibold tracking-wider text-[var(--text-secondary)]"
              style={{ borderColor: badge.dot }}
              aria-hidden="true"
            >
              {badge.label}
            </span>
            <span className="flex flex-col leading-tight max-w-[12rem]">
              <span className="text-[11px] text-[var(--text-primary)] truncate">{name}</span>
              <span className="font-mono text-[9px] text-[var(--text-muted)]">{badge.label}</span>
            </span>
            <button
              type="button"
              onClick={() => toggleSelection(id)}
              aria-label={`Remove ${name} from context`}
              className="w-6 h-6 grid place-items-center rounded text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors text-base leading-none"
            >
              ×
            </button>
          </div>
        );
      })}
      {selectedIds.length > 1 && (
        <button
          type="button"
          onClick={clearSelection}
          className="shrink-0 font-mono text-[10px] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors px-2 py-1"
        >
          clear
        </button>
      )}
    </div>
  );
}
