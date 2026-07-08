import type { CaveatsBlockData } from '../../../types/api';

function Callout({ title, items, tone }: {
  title: string; items: string[]; tone: 'warn' | 'muted';
}) {
  if (!items.length) return null;
  const cls = tone === 'warn'
    ? 'border-amber-500/40 bg-amber-500/10 text-amber-200'
    : 'border-[var(--border)] bg-[var(--bg-primary)]/50 text-[var(--text-secondary)]';
  return (
    <div className={`my-2 rounded-lg border px-3 py-2 text-[11px] ${cls}`}>
      <p className="font-semibold text-[10px] uppercase tracking-wide mb-1 opacity-80">
        {title}
      </p>
      <ul className="list-disc ml-4 space-y-0.5">
        {items.map((it, i) => <li key={i}>{it}</li>)}
      </ul>
    </div>
  );
}

export default function CaveatsBlock({ block }: { block: CaveatsBlockData }) {
  return (
    <>
      <Callout title="Warnings" items={block.warnings ?? []} tone="warn" />
      <Callout title="Caveats" items={block.caveats ?? []} tone="muted" />
    </>
  );
}
