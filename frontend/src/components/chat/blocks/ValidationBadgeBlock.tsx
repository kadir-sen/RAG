import type { ValidationStatusBlock } from '../../../types/api';

const TONE: Record<string, string> = {
  passed: 'text-emerald-400/80',
  failed: 'text-red-300',
  fallback: 'text-amber-300',
  skipped: 'opacity-60',
};

/** One-line validation trail for a block-based answer — mirrors
 * ProgrammeResult's ValidationTrail visual language. */
export default function ValidationBadgeBlock({ block }: { block: ValidationStatusBlock }) {
  const entries = Object.entries(block.guards ?? {});
  if (!entries.length && !block.requires_analyst_review) return null;
  return (
    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-[var(--text-muted)]">
      <span className="uppercase tracking-wide opacity-70">Validation:</span>
      {entries.map(([name, status]) => (
        <span key={name} className={TONE[status] ?? ''}>
          {status === 'passed' ? '✓' : status === 'failed' ? '✗' : '·'} {name.replace(/_/g, ' ')}
        </span>
      ))}
      {block.fallbacks_used?.length > 0 && (
        <span className="text-amber-300/80">
          fallbacks: {block.fallbacks_used.join(', ')}
        </span>
      )}
      {block.requires_analyst_review && (
        <span className="text-[10px] px-1.5 py-0.5 rounded border font-semibold uppercase bg-amber-500/20 text-amber-300 border-amber-500/30">
          analyst review required
        </span>
      )}
    </div>
  );
}
