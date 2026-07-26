import { memo } from 'react';
import type { AppMode } from '../../stores/chatStore';
import { useAuthStore } from '../../stores/authStore';

type ModeOption = 'document_analysis' | 'correspondence';

interface Props {
  activeMode: AppMode;
  onSelect: (mode: ModeOption) => void;
}

const ALL_OPTIONS: { id: ModeOption; label: string; requires?: string }[] = [
  { id: 'document_analysis', label: 'Document Analysis' },
  { id: 'correspondence', label: 'Correspondence', requires: 'correspondence' },
];

/**
 * Compact segmented control rendered inside the sidebar so the chat thread
 * stays free of mode-picker chrome. Persists the selection through
 * `useChatStore.setMode`.
 */
function ModeToggle({ activeMode, onSelect }: Props) {
  const features = useAuthStore((s) => s.user?.features ?? {});
  const options = ALL_OPTIONS.filter((o) => !o.requires || features[o.requires]);

  // If the user only has one available mode, hide the toggle entirely.
  if (options.length <= 1) return null;

  return (
    <div
      data-testid="sidebar-mode-toggle"
      role="radiogroup"
      aria-label="Knowledge base mode"
      className="mx-3 mt-1 mb-1 grid grid-cols-2 rounded-md border border-[var(--border)] bg-[var(--wash)] p-0.5 text-[11px] font-mono"
    >
      {options.map((opt) => {
        const active = activeMode === opt.id;
        return (
          <button
            key={opt.id}
            type="button"
            role="radio"
            aria-checked={active}
            aria-pressed={active}
            onClick={() => onSelect(opt.id)}
            title={opt.label}
            data-mode={opt.id}
            className={`px-2 py-1.5 rounded transition-colors text-center ${
              active
                ? 'bg-[var(--bg-hover)] text-[var(--text-primary)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

export default memo(ModeToggle);
