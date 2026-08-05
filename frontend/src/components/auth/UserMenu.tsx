import { useEffect, useRef, useState } from 'react';
import { useAuthStore } from '../../stores/authStore';
import { useUIStore } from '../../stores/uiStore';

function initial(name: string): string {
  const trimmed = (name || '').trim();
  return trimmed ? trimmed[0].toUpperCase() : 'U';
}

export default function UserMenu() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const toggleSettings = useUIStore((s) => s.toggleSettings);
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (!wrapperRef.current?.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener('mousedown', handler);
    return () => window.removeEventListener('mousedown', handler);
  }, [open]);

  if (!user) {
    return (
      <div
        className="w-11 h-11 rounded-[2px] border border-[var(--border)] grid place-items-center font-mono text-[var(--text-muted)] text-[11px]"
        aria-label="No user"
      >
        ?
      </div>
    );
  }

  return (
    <div className="relative" ref={wrapperRef}>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Account menu for ${user.display_name}`}
        className="w-11 h-11 rounded-[2px] bg-[var(--ink)] flex items-center justify-center font-mono text-[var(--accent-ink)] text-[11px] font-bold hover:opacity-88 transition-opacity"
      >
        {initial(user.display_name || user.username)}
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 mt-2 w-56 bg-[var(--bg-secondary)] border border-[var(--border)] rounded-md shadow-xl z-50 overflow-hidden"
        >
          <div className="px-3 py-3 border-b border-[var(--border)]">
            <div className="text-[13px] text-[var(--text-primary)] font-medium truncate">
              {user.display_name || user.username}
            </div>
            <div className="font-mono text-[10px] text-[var(--text-muted)] tracking-wide truncate mt-0.5">
              {user.username} · {user.role}
            </div>
          </div>
          <button
            role="menuitem"
            onClick={() => {
              setOpen(false);
              toggleSettings();
            }}
            className="w-full text-left px-3 py-3 text-[12px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] font-mono tracking-wide transition-colors sm:hidden"
          >
            Settings
          </button>
          <button
            role="menuitem"
            onClick={() => {
              setOpen(false);
              logout();
              window.location.assign('/login');
            }}
            className="w-full text-left px-3 py-3 text-[12px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] font-mono tracking-wide transition-colors"
          >
            Sign out →
          </button>
        </div>
      )}
    </div>
  );
}
