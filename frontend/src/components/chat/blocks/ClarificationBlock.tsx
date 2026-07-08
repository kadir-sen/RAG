import type { ClarificationBlockData } from '../../../types/api';

/** In-chat clarification: question + option chips. Selecting an option sends
 * it as a normal user message through the existing send pipeline. */
export default function ClarificationBlock({ block, onSend }: {
  block: ClarificationBlockData;
  onSend?: (text: string) => void;
}) {
  return (
    <div className="my-2 rounded-lg border border-[var(--accent)]/40 bg-[var(--accent-glow)] px-3 py-2">
      <p className="text-sm text-[var(--text-primary)] mb-2">{block.question}</p>
      {block.options?.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {block.options.map((o) => (
            <button
              key={o.value}
              onClick={() => onSend?.(o.value)}
              disabled={!onSend}
              className="px-3 py-1.5 text-[11px] rounded-full border border-[var(--accent)]/50 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors disabled:opacity-50"
            >
              {o.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
