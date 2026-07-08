import { useMemo } from 'react';
import type { ChartBlockData } from '../../../types/api';

/** Generic hand-rolled SVG chart block (line + bar) — data-driven, rendered
 * client-side so the backend chart guard can verify values against source.
 * Same visual scaffolding as MilestoneShiftChart (which stays untouched). */

const W = 640;
const H = 300;
const PAD = { top: 20, right: 16, bottom: 48, left: 64 };

const COLORS = [
  '#E89517', '#38bdf8', '#4ade80', '#f472b6',
  '#a78bfa', '#fb923c', '#f87171', '#22d3ee',
];

function toNumeric(v: string | number | null): number | null {
  if (v == null) return null;
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  const t = Date.parse(v);
  if (!Number.isNaN(t) && /\d{4}-\d{2}/.test(v)) return t;
  const n = Number(v);
  return Number.isNaN(n) ? null : n;
}

function fmtTick(v: number, isDate: boolean): string {
  if (isDate) {
    return new Date(v).toLocaleDateString(undefined, { year: '2-digit', month: 'short' });
  }
  return Math.abs(v) >= 1000 ? v.toLocaleString() : String(Math.round(v * 100) / 100);
}

function LineChart({ block }: { block: ChartBlockData }) {
  const model = useMemo(() => {
    const series = block.series ?? [];
    const pts = series.flatMap((s) =>
      s.points
        .map((p) => ({ x: toNumeric(p.x), y: toNumeric(p.y) }))
        .filter((p): p is { x: number; y: number } => p.x != null && p.y != null));
    if (!pts.length) return null;
    const xs = pts.map((p) => p.x); const ys = pts.map((p) => p.y);
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    const y0 = Math.min(...ys), y1 = Math.max(...ys);
    const isDateX = series.some((s) => s.points.some(
      (p) => typeof p.x === 'string' && /\d{4}-\d{2}/.test(p.x)));
    const sx = (t: number) => PAD.left + ((t - x0) / Math.max(1, x1 - x0)) * (W - PAD.left - PAD.right);
    const sy = (t: number) => H - PAD.bottom - ((t - y0) / Math.max(1e-9, y1 - y0)) * (H - PAD.top - PAD.bottom);
    return { x0, x1, y0, y1, sx, sy, isDateX };
  }, [block]);

  if (!model) return null;
  const { x0, x1, y0, y1, sx, sy, isDateX } = model;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[480px]" role="img"
         aria-label={block.title}>
      <line x1={PAD.left} y1={H - PAD.bottom} x2={W - PAD.right} y2={H - PAD.bottom} stroke="var(--border)" />
      <line x1={PAD.left} y1={PAD.top} x2={PAD.left} y2={H - PAD.bottom} stroke="var(--border)" />
      {[x0, (x0 + x1) / 2, x1].map((t) => (
        <text key={`x${t}`} x={sx(t)} y={H - PAD.bottom + 16} textAnchor="middle"
              fontSize="10" fill="var(--text-muted)">{fmtTick(t, isDateX)}</text>
      ))}
      {[y0, (y0 + y1) / 2, y1].map((t) => (
        <text key={`y${t}`} x={PAD.left - 8} y={sy(t) + 3} textAnchor="end"
              fontSize="10" fill="var(--text-muted)">{fmtTick(t, false)}</text>
      ))}
      {(block.series ?? []).map((s, i) => {
        const pts = s.points
          .map((p) => ({ x: toNumeric(p.x), y: toNumeric(p.y) }))
          .filter((p): p is { x: number; y: number } => p.x != null && p.y != null);
        if (!pts.length) return null;
        const color = COLORS[i % COLORS.length];
        return (
          <g key={s.name}>
            <polyline points={pts.map((p) => `${sx(p.x)},${sy(p.y)}`).join(' ')}
                      fill="none" stroke={color} strokeWidth="1.5" />
            {pts.map((p, j) => (
              <circle key={j} cx={sx(p.x)} cy={sy(p.y)} r={2.5}
                      fill="var(--bg-secondary)" stroke={color} strokeWidth="1.5" />
            ))}
          </g>
        );
      })}
    </svg>
  );
}

function BarChart({ block }: { block: ChartBlockData }) {
  const cats = block.categories ?? [];
  const vals = block.values ?? [];
  if (!cats.length || cats.length !== vals.length) return null;
  const maxV = Math.max(...vals, 0);
  const minV = Math.min(...vals, 0);
  const span = Math.max(1e-9, maxV - minV);
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const bw = Math.min(64, (innerW / cats.length) * 0.7);
  const sy = (v: number) => H - PAD.bottom - ((v - minV) / span) * innerH;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[480px]" role="img"
         aria-label={block.title}>
      <line x1={PAD.left} y1={sy(Math.max(0, minV))} x2={W - PAD.right}
            y2={sy(Math.max(0, minV))} stroke="var(--border)" />
      <line x1={PAD.left} y1={PAD.top} x2={PAD.left} y2={H - PAD.bottom} stroke="var(--border)" />
      {[minV, (minV + maxV) / 2, maxV].map((t) => (
        <text key={`y${t}`} x={PAD.left - 8} y={sy(t) + 3} textAnchor="end"
              fontSize="10" fill="var(--text-muted)">{fmtTick(t, false)}</text>
      ))}
      {cats.map((c, i) => {
        const cx = PAD.left + (innerW / cats.length) * (i + 0.5);
        const v = vals[i];
        const yTop = Math.min(sy(v), sy(0));
        const h = Math.abs(sy(v) - sy(0));
        const label = c.length > 12 ? `${c.slice(0, 11)}…` : c;
        return (
          <g key={`${c}-${i}`}>
            <rect x={cx - bw / 2} y={yTop} width={bw} height={Math.max(1, h)}
                  fill={COLORS[0]} opacity={0.85} rx={2} />
            <text x={cx} y={yTop - 4} textAnchor="middle" fontSize="9"
                  fill="var(--text-secondary)">{fmtTick(v, false)}</text>
            <text x={cx} y={H - PAD.bottom + 14} textAnchor="middle" fontSize="9"
                  fill="var(--text-muted)"
                  transform={cats.length > 8 ? `rotate(30 ${cx} ${H - PAD.bottom + 14})` : undefined}>
              {label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export default function ChartBlock({ block }: { block: ChartBlockData }) {
  const body = block.chart_type === 'bar'
    ? <BarChart block={block} />
    : <LineChart block={block} />;
  if (!body) return null;
  return (
    <div className="my-3 rounded-lg border border-[var(--border)] p-3 overflow-x-auto">
      {block.title && (
        <p className="text-[11px] font-medium text-[var(--text-secondary)] mb-1">
          {block.title}
        </p>
      )}
      {body}
      {(block.x_label || block.y_label) && (
        <p className="mt-1 text-[10px] text-[var(--text-muted)]">
          {block.y_label}{block.x_label && block.y_label ? ' — ' : ''}{block.x_label}
        </p>
      )}
      {block.chart_type === 'line' && (block.series?.length ?? 0) > 1 && (
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
          {(block.series ?? []).map((s, i) => (
            <span key={s.name}
                  className="inline-flex items-center gap-1.5 text-[10px] text-[var(--text-muted)]">
              <span className="inline-block w-3 h-0.5"
                    style={{ backgroundColor: COLORS[i % COLORS.length] }} />
              <span className="truncate max-w-[220px]">{s.name}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
