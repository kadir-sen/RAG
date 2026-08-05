import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

/**
 * One module tile — Netflix's "who's watching", drawn in drafting terms.
 *
 * A square mark on its own sheet, a caption beneath. On hover the hairline
 * thickens to ink and registration marks strike in at two corners, the way a
 * drawing is squared up before it is worked on. Follows the portal's tile
 * (delay-disputes-portal/index.html + styles.css §.tile) so the platform and
 * the app read as one document set, but rebuilt on this app's tokens rather
 * than copying the portal's stylesheet.
 *
 * A disabled tile is a real <div>, not a dead link: nothing to tab to, and
 * aria-disabled tells a screen reader why it is inert.
 */
interface Props {
  index: string;
  name: string;
  role: string;
  blurb: string;
  mark: ReactNode;
  to?: string;
  /** An external destination. Renders a plain <a> rather than a router Link,
      and deliberately without target="_blank" — the ask was for it to open in
      the same window, as if it were part of this app. */
  href?: string;
  status?: 'live' | 'soon';
  statusLabel?: string;
}

export default function ModuleTile({
  index,
  name,
  role,
  blurb,
  mark,
  to,
  href,
  status = 'live',
  statusLabel,
}: Props) {
  const disabled = !to && !href;

  const body = (
    <>
      <span
        className={`tile-mark relative block h-20 w-20 flex-none border overflow-hidden transition-all duration-150 sm:h-auto sm:w-full sm:max-w-[132px] sm:aspect-square sm:self-center lg:max-w-none ${
          disabled
            ? 'border-[var(--border)] opacity-40'
            : 'border-[var(--border)] group-hover:border-[var(--ink)] group-focus-visible:border-[var(--ink)]'
        }`}
      >
        {mark}
        {/* Registration marks — struck in only on hover/focus. */}
        {!disabled && (
          <>
            <span className="pointer-events-none absolute top-1.5 left-1.5 w-3.5 h-3.5 border-t-2 border-l-2 border-[var(--ink)] opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus-visible:opacity-100" />
            <span className="pointer-events-none absolute bottom-1.5 right-1.5 w-3.5 h-3.5 border-b-2 border-r-2 border-[var(--ink)] opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus-visible:opacity-100" />
          </>
        )}
      </span>

      <span className="flex min-w-0 flex-1 flex-col gap-1 sm:flex-none">
        <span className="flex items-baseline gap-2">
          <span className="font-mono text-[10px] tabular-nums tracking-[0.18em] text-[var(--text-muted)]">
            {index}
          </span>
          <span
            className={`text-[15px] font-semibold ${
              disabled ? 'text-[var(--text-muted)]' : 'text-[var(--text-primary)]'
            }`}
          >
            {name}
          </span>
        </span>
        <span className="font-mono text-[10px] tracking-[0.14em] uppercase text-[var(--text-secondary)]">
          {role}
        </span>
        <span className="text-[12px] leading-5 text-[var(--text-muted)]">{blurb}</span>
        <span
          className={`mt-1 self-start px-1.5 py-0.5 border rounded-[2px] font-mono text-[9px] tracking-[0.18em] uppercase ${
            status === 'live'
              ? 'border-[var(--accent-green)] text-[var(--accent-green)]'
              : 'border-[var(--border)] text-[var(--text-muted)]'
          }`}
        >
          {statusLabel ?? (status === 'live' ? 'Live' : 'Soon')}
        </span>
      </span>
    </>
  );

  const shared = 'group flex min-h-20 flex-row items-start gap-3.5 text-left sm:flex-col';

  if (to) {
    return (
      <Link to={to} className={`${shared} no-underline focus:outline-none`} data-module={name}>
        {body}
      </Link>
    );
  }

  if (href) {
    return (
      <a href={href} className={`${shared} no-underline focus:outline-none`} data-module={name}>
        {body}
      </a>
    );
  }

  return (
    <div className={`${shared} cursor-not-allowed`} aria-disabled="true">
      {body}
    </div>
  );
}
