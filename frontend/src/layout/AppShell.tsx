import type React from 'react';
import TopNav from './TopNav';

export default function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="h-full w-full flex flex-col overflow-clip bg-[var(--bg-primary)]">
      <a href="#main-content" className="skip-link">
        Skip to main content
      </a>
      <TopNav />
      <main id="main-content" className="flex-1 flex overflow-hidden min-h-0">
        {children}
      </main>
    </div>
  );
}
