import { useUIStore } from '../stores/uiStore';
import UsageRing from '../components/shared/UsageRing';
import BrandMark from '../components/shared/BrandMark';
import SheetToggle from '../components/shared/SheetToggle';
import UserMenu from '../components/auth/UserMenu';
import ProjectSelector from '../components/projects/ProjectSelector';
import { useLocation, useNavigate } from 'react-router-dom';

export default function TopNav() {
  const location = useLocation();
  const navigate = useNavigate();
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const toggleSettings = useUIStore((s) => s.toggleSettings);
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);

  return (
    <header
      data-testid="topnav"
      className="grid grid-cols-[minmax(0,1fr)_auto] grid-rows-2 items-center gap-x-1 px-2 py-1 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] md:grid-rows-1 md:px-4 md:py-0 border-b border-[var(--border)] flex-shrink-0 bg-[var(--bg-primary)]"
      style={{ height: 'var(--topnav-height)' }}
    >
      {/* Left — the selected project is the persistent workspace context. */}
      <nav aria-label="Workspace navigation" className="col-span-2 row-start-1 flex w-full min-w-0 items-center gap-1.5 justify-self-start md:col-span-1 md:w-auto">
        {location.pathname !== '/' && (
          <button
            type="button"
            onClick={() => navigate('/')}
            aria-label="Back to main menu"
            title="Back to main menu"
            className="w-11 h-11 shrink-0 flex items-center justify-center border border-[var(--border)] rounded-[2px] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--ink)] hover:bg-[var(--bg-hover)] transition-colors"
          >
            <svg aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="m15 18-6-6 6-6" />
            </svg>
          </button>
        )}
        <ProjectSelector />
        {location.pathname === '/chat' && <button
          onClick={toggleSidebar}
          aria-label={sidebarOpen ? 'Close sidebar' : 'Open sidebar'}
          aria-expanded={sidebarOpen}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors"
        >
          {sidebarOpen ? (
            <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <line x1="9" y1="3" x2="9" y2="21" />
              <path d="M14 9l-3 3 3 3" />
            </svg>
          ) : (
            <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <line x1="9" y1="3" x2="9" y2="21" />
              <path d="M14 9l3 3-3 3" />
            </svg>
          )}
        </button>}
      </nav>

      {/* Center — wordmark + workspace label */}
      <div className="hidden md:flex items-center gap-2 justify-self-center">
        <BrandMark size="sm" />
      </div>

      {/* Right — usage badge + sheet toggle + settings + avatar */}
      <div data-testid="topnav-actions" className="col-start-2 row-start-2 flex items-center gap-1 justify-self-end text-[var(--text-secondary)] md:col-start-3 md:row-start-1 md:gap-2">
        <UsageRing size={16} showLabel />
        <SheetToggle />
        <button
          onClick={toggleSettings}
          aria-label="Open settings"
          className="hidden w-11 h-11 items-center justify-center rounded-md hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors sm:flex"
        >
          <svg aria-hidden="true" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
            <path d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <UserMenu />
      </div>
    </header>
  );
}
