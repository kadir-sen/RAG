import type React from 'react';
import TopNav from './TopNav';
import DocumentViewerHost from '../components/viewer/DocumentViewerHost';

export default function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="h-dvh min-h-0 w-full max-w-full flex flex-col overflow-clip bg-[var(--bg-primary)]">
      <a href="#main-content" className="skip-link">
        Skip to main content
      </a>
      <TopNav />
      {/* The app ground is a drawing sheet: the blue-line grid runs under
          everything, and cards drawn on it let it faintly show through. */}
      <main id="main-content" className="sheet-grid flex min-h-0 min-w-0 flex-1 overflow-hidden">
        <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">{children}</div>
        <DocumentViewerHost />
      </main>
    </div>
  );
}
