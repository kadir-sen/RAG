import { useUIStore } from '../stores/uiStore';

export default function TopNav() {
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const toggleSettings = useUIStore((s) => s.toggleSettings);
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);

  return (
    <header className="h-14 flex items-center justify-between px-4 border-b border-[var(--border)] flex-shrink-0 bg-[var(--bg-secondary)]">
      {/* Left — toggle + branding */}
      <nav aria-label="Main navigation" className="flex items-center gap-3">
        <button
          onClick={toggleSidebar}
          aria-label={sidebarOpen ? 'Close sidebar' : 'Open sidebar'}
          aria-expanded={sidebarOpen}
          className="w-8 h-8 flex items-center justify-center rounded-lg text-[var(--text-secondary)] hover:text-white hover:bg-[var(--bg-hover)] transition-colors"
        >
          {sidebarOpen ? (
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <line x1="9" y1="3" x2="9" y2="21" />
              <path d="M14 9l-3 3 3 3" />
            </svg>
          ) : (
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <line x1="9" y1="3" x2="9" y2="21" />
              <path d="M14 9l3 3-3 3" />
            </svg>
          )}
        </button>
        <div className="flex items-center gap-1.5" aria-label="ConstructionIQ">
          <span className="font-semibold text-sm text-white">Construction</span>
          <span className="font-semibold text-sm text-[var(--accent)]">IQ</span>
        </div>
      </nav>

      {/* Right — settings + avatar */}
      <div className="flex items-center gap-3 text-[var(--text-secondary)]">
        <button
          onClick={toggleSettings}
          aria-label="Open settings"
          className="w-8 h-8 flex items-center justify-center rounded-lg hover:text-white hover:bg-[var(--bg-hover)] transition-colors"
        >
          <svg aria-hidden="true" className="w-[18px] h-[18px]" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
            <path d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <div className="w-7 h-7 rounded-full bg-[var(--accent)] flex items-center justify-center text-white text-xs font-medium" aria-label="User avatar">
          U
        </div>
      </div>
    </header>
  );
}
