import { memo } from 'react';

type Variant = 'assistant' | 'user';

interface Props {
  variant: Variant;
  initials?: string;
}

function Avatar({ variant, initials }: Props) {
  const label = initials ?? (variant === 'assistant' ? 'A' : 'U');
  const gradient =
    variant === 'assistant'
      ? 'from-[#6366F1] to-[#A855F7]'
      : 'from-[#7C3AED] to-[#9333EA]';
  return (
    <div
      aria-hidden="true"
      className={`shrink-0 rounded-full bg-gradient-to-br ${gradient} text-white text-[11px] font-semibold flex items-center justify-center select-none`}
      style={{ width: 'var(--avatar-size)', height: 'var(--avatar-size)' }}
    >
      {label}
    </div>
  );
}

export default memo(Avatar);
