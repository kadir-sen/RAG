import { useState } from 'react';
import type {
  ProgrammeArtifact,
  ProgrammeChart,
  ProgrammeTable,
  ProgrammeToolResult,
} from '../../types/api';
import { downloadArtifact } from '../../api/fileApi';
import MilestoneShiftChart from './MilestoneShiftChart';

/** Renders deterministic programme-analysis output (single ToolResult or a
 * workflow pack with sections): tables, SVG chart, warnings/caveats callouts,
 * analyst-review badge and artifact downloads. Table styling mirrors
 * SqlArtifact.tsx. */

function StatusBadge({ status }: { status: string }) {
  const cls =
    status === 'complete'
      ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30'
      : status === 'partial'
        ? 'bg-amber-500/20 text-amber-300 border-amber-500/30'
        : 'bg-red-500/20 text-red-300 border-red-500/30';
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded border font-semibold uppercase ${cls}`}>
      {status}
    </span>
  );
}

function ResultTable({ table }: { table: ProgrammeTable }) {
  return (
    <div className="my-3">
      <p className="text-[11px] font-medium text-[var(--text-secondary)] mb-1">
        {table.title}
      </p>
      <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
        <table className="w-full text-xs">
          <thead className="bg-[var(--bg-primary)]">
            <tr>
              {table.columns.map((c) => (
                <th key={c}
                    className="px-3 py-2 text-left text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wider border-b border-[var(--border)]">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, i) => (
              <tr key={i}
                  className="even:bg-[var(--bg-primary)]/30 hover:bg-[var(--bg-hover)] transition-colors">
                {row.map((cell, j) => (
                  <td key={j}
                      className="px-3 py-1.5 text-[var(--text-primary)] border-b border-[var(--border)]/50 whitespace-nowrap">
                    {cell ?? '—'}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

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

const NARRATIVE_GUARD_LABELS: Record<string, string> = {
  approved: 'narrative validated',
  rewritten_then_approved: 'narrative validated (after rewrite)',
  fallback_after_rejection: 'narrative rejected — showing computed results',
  llm_unavailable: 'narrative unavailable — computed results only',
  deterministic_only: 'computed results only',
};

function ValidationTrail({ result }: { result: ProgrammeToolResult }) {
  const v = result.validation;
  if (!v || (!v.computation_guard && !v.narrative_guard)) return null;
  const comp = v.computation_guard;
  const narr = v.narrative_guard;
  const compOk = comp?.pre !== 'failed' && comp?.post !== 'violations';
  return (
    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-[var(--text-muted)]">
      <span className="uppercase tracking-wide opacity-70">Validation:</span>
      {comp && (
        <span className={compOk ? 'text-emerald-400/80' : 'text-amber-300'}>
          {compOk ? '✓ computation checks passed'
                  : `⚠ computation checks: ${(comp.violations ?? []).length} issue(s)`}
        </span>
      )}
      {narr && (
        <span className={narr.status.startsWith('approved') || narr.status === 'rewritten_then_approved'
          ? 'text-emerald-400/80' : 'opacity-80'}>
          {narr.status === 'approved' || narr.status === 'rewritten_then_approved' ? '✓ ' : '· '}
          {NARRATIVE_GUARD_LABELS[narr.status] ?? narr.status}
        </span>
      )}
    </div>
  );
}

function ToolResultBody({ result }: { result: ProgrammeToolResult }) {
  return (
    <>
      <div className="flex items-center gap-2 flex-wrap">
        <StatusBadge status={result.status} />
        {result.requires_analyst_review && (
          <span className="text-[10px] px-1.5 py-0.5 rounded border font-semibold uppercase bg-amber-500/20 text-amber-300 border-amber-500/30">
            analyst review required
          </span>
        )}
        <span className="text-[11px] text-[var(--text-muted)]">{result.summary}</span>
      </div>
      <ValidationTrail result={result} />
      {result.tables?.map((t) => <ResultTable key={t.title} table={t} />)}
      {result.charts?.map((c: ProgrammeChart) => (
        <MilestoneShiftChart key={c.chart_id} chart={c} />
      ))}
      <Callout title="Warnings" items={result.warnings ?? []} tone="warn" />
      <Callout title="Caveats" items={result.caveats ?? []} tone="muted" />
      {!!result.artifacts?.length && (
        <div className="mt-2 flex flex-wrap gap-2">
          {result.artifacts.map((a) => (
            <button
              key={a.artifact_id}
              onClick={() => void downloadArtifact(a.url, a.filename)}
              className="px-3 py-1.5 text-[11px] rounded-md border border-[var(--border)] hover:bg-[var(--bg-hover)] hover:border-[var(--accent)]/50 transition-colors text-[var(--text-secondary)]"
            >
              ⤓ {a.filename}
            </button>
          ))}
        </div>
      )}
    </>
  );
}

function PackSection({ title, children }: {
  title: string; children: React.ReactNode;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div className="my-2 rounded-lg border border-[var(--border)]">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full px-3 py-2 text-left text-xs font-semibold text-[var(--text-primary)] hover:bg-[var(--bg-hover)] flex items-center justify-between"
      >
        {title}
        <span className="text-[var(--text-muted)]">{open ? '−' : '+'}</span>
      </button>
      {open && <div className="px-3 pb-3">{children}</div>}
    </div>
  );
}

export default function ProgrammeResult({ artifact }: { artifact: ProgrammeArtifact }) {
  // Workflow pack → sections; single tool → one body.
  if (artifact.sections) {
    return (
      <div className="mt-3">
        {artifact.sections.map((s) => (
          <PackSection key={s.section_id} title={s.title}>
            {s.tool_result
              ? <ToolResultBody result={s.tool_result} />
              : <p className="text-[11px] text-[var(--text-muted)]">{s.narrative}</p>}
          </PackSection>
        ))}
      </div>
    );
  }
  return (
    <div className="mt-3">
      <ToolResultBody result={artifact as ProgrammeToolResult} />
    </div>
  );
}
