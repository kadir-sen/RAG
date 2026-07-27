import { useId } from 'react';
import type { ChartSpec } from '../../types/api';

/**
 * A SQL result, drawn.
 *
 * Hand-written SVG rather than a charting library: the app ships no charting
 * dependency, and the ones worth having are larger than this whole component.
 * It also means the chart is drawn in the sheet's own terms — hairline axes,
 * tracked mono labels, tabular figures, square ends — instead of fighting a
 * library's defaults. Same approach as UsageRing.
 *
 * Everything is a token, so it follows the drawing sheet and the blueprint
 * without a second definition.
 */

interface Props {
  spec: ChartSpec;
  rows: Record<string, unknown>[];
}

const W = 640;
const H = 220;
const PAD = { top: 16, right: 12, bottom: 34, left: 52 };

/* Series colours: file-type and status tokens, which are the only multi-hue
   set the palette defines. Emphasis is ink, so the first series is ink. */
const SERIES = ['var(--ink)', 'var(--accent-green)', 'var(--warning)'];

function niceCeil(v: number): number {
  if (v <= 0) return 1;
  const mag = 10 ** Math.floor(Math.log10(v));
  return Math.ceil(v / mag) * mag;
}

function fmt(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(0)}k`;
  return String(Math.round(n * 100) / 100);
}

export default function ChartBlock({ spec, rows }: Props) {
  const clipId = useId();
  const series = spec.y.filter((k) => k in (rows[0] ?? {}));
  if (!rows.length || !series.length) return null;

  const num = (r: Record<string, unknown>, k: string) => {
    const v = r[k];
    return typeof v === 'number' && Number.isFinite(v) ? v : 0;
  };

  const max = niceCeil(Math.max(...rows.flatMap((r) => series.map((k) => num(r, k))), 0));
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const yOf = (v: number) => PAD.top + plotH - (v / max) * plotH;
  const bandW = plotW / rows.length;

  /* Enough ticks to read the scale, few enough to stay quiet. */
  const ticks = [0, 0.5, 1].map((f) => max * f);

  /* Long category names would collide; show every nth when crowded. */
  const labelEvery = Math.ceil(rows.length / 8);

  return (
    <figure className="mt-3 mb-0">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full h-auto"
        role="img"
        aria-label={`${spec.type} chart of ${series.join(', ')} by ${spec.x}`}
      >
        <defs>
          <clipPath id={clipId}>
            <rect x={PAD.left} y={PAD.top} width={plotW} height={plotH} />
          </clipPath>
        </defs>

        {/* value axis — hairline rules, mono figures */}
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={yOf(t)}
              y2={yOf(t)}
              stroke="var(--border)"
              strokeWidth="1"
            />
            <text
              x={PAD.left - 8}
              y={yOf(t) + 3}
              textAnchor="end"
              className="font-mono"
              fontSize="9"
              fill="var(--text-muted)"
            >
              {fmt(t)}
            </text>
          </g>
        ))}

        {/* the baseline is struck in to ink — it is the reference, not a gridline */}
        <line
          x1={PAD.left}
          x2={W - PAD.right}
          y1={yOf(0)}
          y2={yOf(0)}
          stroke="var(--ink)"
          strokeWidth="1"
        />

        <g clipPath={`url(#${clipId})`}>
          {spec.type === 'line'
            ? series.map((key, si) => (
                <polyline
                  key={key}
                  fill="none"
                  stroke={SERIES[si % SERIES.length]}
                  strokeWidth="2"
                  strokeLinecap="square"
                  strokeLinejoin="miter"
                  points={rows
                    .map((r, i) => `${PAD.left + bandW * (i + 0.5)},${yOf(num(r, key))}`)
                    .join(' ')}
                />
              ))
            : rows.map((r, i) =>
                series.map((key, si) => {
                  const w = (bandW * 0.62) / series.length;
                  const x = PAD.left + bandW * i + bandW * 0.19 + w * si;
                  const y = yOf(num(r, key));
                  return (
                    <rect
                      key={`${i}-${key}`}
                      x={x}
                      y={y}
                      width={Math.max(1, w - 1)}
                      height={Math.max(0, yOf(0) - y)}
                      fill={SERIES[si % SERIES.length]}
                    />
                  );
                }),
              )}
        </g>

        {/* category axis */}
        {rows.map((r, i) =>
          i % labelEvery === 0 ? (
            <text
              key={i}
              x={PAD.left + bandW * (i + 0.5)}
              y={H - PAD.bottom + 14}
              textAnchor="middle"
              className="font-mono"
              fontSize="9"
              fill="var(--text-muted)"
            >
              {String(r[spec.x] ?? '').slice(0, 12)}
            </text>
          ) : null,
        )}
      </svg>

      <figcaption className="mt-1.5 flex flex-wrap items-center gap-3">
        {series.map((key, si) => (
          <span key={key} className="inline-flex items-center gap-1.5">
            <span
              className="w-2.5 h-2.5 shrink-0"
              style={{ background: SERIES[si % SERIES.length] }}
              aria-hidden="true"
            />
            <span className="font-mono text-[10px] tracking-[0.12em] uppercase text-[var(--text-secondary)]">
              {key}
            </span>
          </span>
        ))}
        <span className="font-mono text-[10px] tracking-[0.12em] uppercase text-[var(--text-muted)] ml-auto">
          by {spec.x}
        </span>
      </figcaption>
    </figure>
  );
}
