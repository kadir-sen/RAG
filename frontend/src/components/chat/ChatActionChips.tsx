import type { AppMode } from '../../stores/chatStore';

interface Props {
  activeMode: AppMode | null;
  onModeSelect: (mode: AppMode) => void;
}

const CHIPS: Array<{ mode: AppMode; label: string; symbol: string }> = [
  { mode: 'correspondence', label: 'Correspondence', symbol: '✉' },
  { mode: 'document_analysis', label: 'Document Analysis', symbol: '▤' },
];

export default function ChatActionChips({ activeMode, onModeSelect }: Props) {
  return (
    <div className="px-4 md:px-6 pt-2 flex-shrink-0">
      <div className="max-w-5xl mx-auto flex flex-wrap items-center gap-2">
        <span className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-muted)] mr-1">
          Programs
        </span>
        {CHIPS.map((chip) => {
          const isActive = activeMode === chip.mode;
          return (
            <button
              key={chip.mode}
              type="button"
              aria-pressed={isActive}
              onClick={() => onModeSelect(chip.mode)}
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium tracking-wide border transition-colors ${
                isActive
                  ? 'bg-[var(--accent-glow)] border-[var(--accent)] text-white'
                  : 'bg-[rgba(255,255,255,0.03)] border-[var(--border)] text-[var(--text-secondary)] hover:text-white hover:bg-[rgba(255,255,255,0.06)]'
              }`}
            >
              <span aria-hidden="true">{chip.symbol}</span>
              <span>{chip.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
