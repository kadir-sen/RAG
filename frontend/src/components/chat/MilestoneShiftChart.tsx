import { useMemo } from 'react';
import type { ProgrammeChart } from '../../types/api';

/** Hand-rolled SVG line chart for milestone shift series.
 * x = revision data date, y = milestone forecast/actual date; a dot marks an
 * achieved (actual) milestone. No chart library — one chart type doesn't
 * justify a dependency. */

const W = 640;
const H = 300;
const PAD = { top: 16, right: 16, bottom: 40, left: 76 };

const COLORS = [
  '#E89517', '#38bdf8', '#4ade80', '#f472b6',
  '#a78bfa', '#fb923c', '#f87171', '#22d3ee',
];

function parseDate(iso: string | number | null): number | null {
  if (iso == null) return null;
  const t = Date.parse(String(iso));
  return Number.isNaN(t) ? null : t;
}

function fmtDate(t: number): string {
  return new Date(t).toLocaleDateString(undefined, {
    year: '2-digit', month: 'short',
  });
}

export default function MilestoneShiftChart({ chart }: { chart: ProgrammeChart }) {
  const model = useMemo(() => {
    const pts = chart.series.flatMap((s) =>
      s.points
        .map((p) => ({ x: parseDate(p.x), y: parseDate(p.y) }))
        .filter((p): p is { x: number; y: number } => p.x != null && p.y != null),
    );
    if (!pts.length) return null;
    const xs = pts.map((p) => p.x);
    const ys = pts.map((p) => p.y);
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    const y0 = Math.min(...ys), y1 = Math.max(...ys);
    const sx = (t: number) =>
      PAD.left + ((t - x0) / Math.max(1, x1 - x0)) * (W - PAD.left - PAD.right);
    const sy = (t: number) =>
      H - PAD.bottom - ((t - y0) / Math.max(1, y1 - y0)) * (H - PAD.top - PAD.bottom);
    return { x0, x1, y0, y1, sx, sy };
  }, [chart]);

  if (!model) return null;
  const { x0, x1, y0, y1, sx, sy } = model;
  const xTicks = [x0, (x0 + x1) / 2, x1];
  const yTicks = [y0, (y0 + y1) / 2, y1];

  return (
    <div className="my-3 rounded-lg border border-[var(--border)] p-3 overflow-x-auto">
      <p className="text-[11px] font-medium text-[var(--text-secondary)] mb-1">
        {chart.title}
      </p>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[480px]"
           role="img" aria-label={chart.title}>
        {/* axes */}
        <line x1={PAD.left} y1={H - PAD.bottom} x2={W - PAD.right}
              y2={H - PAD.bottom} stroke="var(--border)" />
        <line x1={PAD.left} y1={PAD.top} x2={PAD.left} y2={H - PAD.bottom}
              stroke="var(--border)" />
        {xTicks.map((t) => (
          <text key={`x${t}`} x={sx(t)} y={H - PAD.bottom + 16}
                textAnchor="middle" fontSize="10" fill="var(--text-muted)">
            {fmtDate(t)}
          </text>
        ))}
        {yTicks.map((t) => (
          <text key={`y${t}`} x={PAD.left - 8} y={sy(t) + 3} textAnchor="end"
                fontSize="10" fill="var(--text-muted)">
            {fmtDate(t)}
          </text>
        ))}
        {/* series */}
        {chart.series.map((s, i) => {
          const pts = s.points
            .map((p) => ({ x: parseDate(p.x), y: parseDate(p.y), marker: p.marker }))
            .filter((p): p is { x: number; y: number; marker: string | null | undefined } =>
              p.x != null && p.y != null);
          if (!pts.length) return null;
          const color = COLORS[i % COLORS.length];
          const path = pts.map((p) => `${sx(p.x)},${sy(p.y)}`).join(' ');
          return (
            <g key={s.name}>
              <polyline points={path} fill="none" stroke={color}
                        strokeWidth="1.5" />
              {pts.map((p, j) => (
                <circle key={j} cx={sx(p.x)} cy={sy(p.y)}
                        r={p.marker === 'achieved' ? 4 : 2.5}
                        fill={p.marker === 'achieved' ? color : 'var(--bg-secondary)'}
                        stroke={color} strokeWidth="1.5" />
              ))}
            </g>
          );
        })}
      </svg>
      {/* legend */}
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
        {chart.series.map((s, i) => (
          <span key={s.name}
                className="inline-flex items-center gap-1.5 text-[10px] text-[var(--text-muted)]">
            <span className="inline-block w-3 h-0.5"
                  style={{ backgroundColor: COLORS[i % COLORS.length] }} />
            <span className="truncate max-w-[220px]">{s.name}</span>
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5 text-[10px] text-[var(--text-muted)]">
          <span className="inline-block w-2 h-2 rounded-full border"
                style={{ backgroundColor: COLORS[0], borderColor: COLORS[0] }} />
          achieved (actual)
        </span>
      </div>
    </div>
  );
}
