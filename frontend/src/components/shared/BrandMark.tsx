/**
 * COAir brand mark.
 *
 * Renders the wordmark with the "CO" prefix (text-primary) + orange
 * "Air" suffix — mirrors the supplied logo. The feather is intentionally
 * omitted at inline sizes to keep the lockup legible; use the standalone
 * `FeatherIcon` (below) wherever the feather mark itself is wanted.
 */
interface Props {
  size?: 'sm' | 'md' | 'lg';
  className?: string;
  showFeather?: boolean;
}

const SIZES = {
  sm: { text: 'text-sm', feather: 16 },
  md: { text: 'text-base', feather: 20 },
  lg: { text: 'text-3xl md:text-4xl', feather: 36 },
} as const;

export default function BrandMark({ size = 'sm', className = '', showFeather = false }: Props) {
  const cfg = SIZES[size];
  return (
    <div
      aria-label="COAir"
      className={`inline-flex items-center gap-1.5 font-extrabold tracking-tight ${cfg.text} ${className}`}
    >
      <span className="leading-none">
        <span className="text-[var(--text-primary)]">CO</span>
        <span className="text-[var(--accent)]">Air</span>
      </span>
      {showFeather && <FeatherIcon size={cfg.feather} />}
    </div>
  );
}

export function FeatherIcon({ size = 18 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {/* Stylised quill vane */}
      <path d="M20 4c-9 1-13 7-15 14L7 20l3-1c7-2 12-7 10-15z" fill="var(--text-primary)" stroke="none" />
      {/* Orange quill spine */}
      <path d="M20 4 L 7 17" stroke="var(--accent)" />
      <path d="M11 13 L 14 15" stroke="var(--accent)" />
      <path d="M14 9 L 18 11" stroke="var(--accent)" />
    </svg>
  );
}
