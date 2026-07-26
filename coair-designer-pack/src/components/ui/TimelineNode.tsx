interface Props {
  type: string;            // short label rendered inside the ring (e.g. "EML")
  color: string;           // ring color (CSS), e.g. var(--type-eml)
  highlight?: boolean;     // filled ring + accent glow
  showRailBelow?: boolean; // connect down to the next node
  className?: string;
}

// Timeline node shared by Document Analysis (vertical roadmap) and the
// Correspondence email-trace digest. 22px circle with 2px ring +
// optional accent glow on highlight. Vertical rail extends downward when
// `showRailBelow` is true.
export default function TimelineNode({
  type,
  color,
  highlight = false,
  showRailBelow = false,
  className = '',
}: Props) {
  return (
    <div className={`relative flex justify-center ${className}`}>
      {showRailBelow && (
        <span
          aria-hidden="true"
          className="absolute top-5 bottom-[-16px] w-px bg-[var(--border-light)] opacity-60"
        />
      )}
      <span
        className="relative z-[1] mt-1 w-5 h-5 grid place-items-center rounded-full font-mono text-[7px] font-bold tracking-wide"
        style={{
          background: highlight ? 'var(--accent)' : 'transparent',
          border: `2px solid ${color}`,
          color: highlight ? 'var(--accent-ink)' : color,
          boxShadow: highlight
            ? '0 0 0 3px var(--wash-firm)'
            : undefined,
        }}
      >
        {type}
      </span>
    </div>
  );
}
