export default function Skeleton({ className = '' }: { className?: string }) {
  return (
    <div
      className={`animate-pulse bg-[var(--bg-surface)] rounded ${className}`}
    />
  );
}
