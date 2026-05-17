import { memo, type ReactNode } from 'react';

interface Props {
  title: string;
  trailing?: ReactNode;
}

/**
 * Mono uppercase section header used between sidebar groups
 * (KNOWLEDGE BASE, RECENT QUERIES, etc.). Matches the reference mockup.
 */
function SidebarSection({ title, trailing }: Props) {
  return (
    <div className="px-5 pt-4 pb-1 shrink-0 flex items-center justify-between">
      <p className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-muted)]">
        {title}
      </p>
      {trailing}
    </div>
  );
}

export default memo(SidebarSection);
