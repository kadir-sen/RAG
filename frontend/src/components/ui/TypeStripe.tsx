interface Props {
  color: string;          // CSS color (e.g. var(--type-pdf))
  height?: number;        // default 2
  className?: string;
}

// 2px coloured top stripe used by the document viewer to identify file type
// (XLS green, PDF red, EML blue) — wireframes.jsx ViewerExcel/Pdf/Email.
export default function TypeStripe({ color, height = 2, className = '' }: Props) {
  return (
    <div
      aria-hidden="true"
      className={`shrink-0 ${className}`}
      style={{ height, background: color }}
    />
  );
}
