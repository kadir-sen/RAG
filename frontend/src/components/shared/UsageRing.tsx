import { useEffect } from 'react';
import { useAuthStore } from '../../stores/authStore';

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function formatCredits(n: number): string {
  return n.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

interface UsageRingProps {
  size?: number;
  showLabel?: boolean;
  showTokens?: boolean;   // render the actual "used / limit" token counts inline
}

export default function UsageRing({ size = 18, showLabel = false, showTokens = false }: UsageRingProps) {
  const user = useAuthStore((s) => s.user);
  const refreshMe = useAuthStore((s) => s.refreshMe);

  useEffect(() => {
    if (!user) return;
    const id = setInterval(() => {
      void refreshMe();
    }, 60_000);
    return () => clearInterval(id);
  }, [user, refreshMe]);

  if (!user) return null;

  // Prefer the backend-supplied percentage, but fall back to deriving it from
  // the token counts when it's missing or non-numeric (e.g. a user object
  // persisted before this field existed). Without this guard the arc renders
  // empty and the label reads "NaN%", which is what made the ring look broken.
  const isDemo = user.plan_type === 'demo';
  const remaining = (() => {
    if (isDemo) {
      const p = Number(user.credit_percent_remaining);
      return Number.isFinite(p) ? Math.max(0, Math.min(100, p)) : 0;
    }
    const p = Number(user.percent_remaining);
    if (Number.isFinite(p)) return Math.max(0, Math.min(100, p));
    if (user.token_limit > 0) {
      return Math.max(0, Math.min(100, (1 - user.used_tokens / user.token_limit) * 100));
    }
    return 100;
  })();
  const remainingTokens = Math.max(0, user.token_limit - user.used_tokens);

  let strokeColor = 'var(--accent)';
  let textClass = 'text-[var(--text-secondary)]';
  if (remaining < 10) {
    strokeColor = 'var(--danger)';
    textClass = 'text-[var(--danger)]';
  } else if (remaining < 30) {
    strokeColor = 'var(--warning)';
    textClass = 'text-[var(--warning)]';
  }

  const strokeWidth = Math.max(2, Math.round(size / 9));
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference * (1 - remaining / 100);
  const center = size / 2;

  const title = isDemo
    ? [
        `${remaining.toFixed(1)}% credit remaining`,
        `${formatCredits(user.credits_remaining)} of ${formatCredits(user.credits_total)} credits left`,
        `Used so far: ${formatCredits(user.credits_used)} credits`,
      ].join('\n')
    : [
        `${remaining.toFixed(1)}% quota remaining`,
        `${formatTokens(remainingTokens)} of ${formatTokens(user.token_limit)} tokens left`,
        `Used so far: ${formatTokens(user.used_tokens)}`,
      ].join('\n');

  return (
    <span
      className="inline-flex items-center gap-1.5"
      title={title}
      aria-label={`${isDemo ? 'Credit balance' : 'Token quota'}: ${remaining.toFixed(0)}% remaining`}
      role="img"
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className="shrink-0"
        aria-hidden="true"
      >
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke="var(--border)"
          strokeWidth={strokeWidth}
        />
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke={strokeColor}
          strokeWidth={strokeWidth}
          strokeLinecap="butt"
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          transform={`rotate(-90 ${center} ${center})`}
          style={{ transition: 'stroke-dashoffset 300ms ease, stroke 300ms ease' }}
        />
      </svg>
      {showLabel && (
        <span className={`hidden font-mono text-[10px] tracking-wider tabular-nums md:inline ${textClass}`}>
          {remaining.toFixed(0)}%
        </span>
      )}
      {showTokens && (
        <span className="font-mono text-[10px] tabular-nums text-[var(--text-muted)]">
          {isDemo
            ? `${formatCredits(user.credits_remaining)}/${formatCredits(user.credits_total)} cr`
            : `${formatTokens(user.used_tokens)}/${formatTokens(user.token_limit)}`}
        </span>
      )}
    </span>
  );
}
