import type React from 'react';
import TopNav from './TopNav';

export default function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden bg-[var(--bg-primary)]">
      <TopNav />
      <div className="flex-1 flex overflow-hidden min-h-0">
        {children}
      </div>
    </div>
  );
}
