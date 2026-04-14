import { useEffect, useRef } from 'react';
import { useUIStore } from '../../stores/uiStore';

const providers = [
  { name: 'Gemini', model: 'gemini-2.5-flash', env: 'GOOGLE_API_KEY', primary: true },
  { name: 'OpenAI', model: 'gpt-4o-mini', env: 'OPENAI_API_KEY', primary: false },
  { name: 'Claude', model: 'claude-sonnet', env: 'ANTHROPIC_API_KEY', primary: false },
];

export default function SettingsModal() {
  const { settingsOpen, toggleSettings } = useUIStore();
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  // Focus trap and Escape key handling
  useEffect(() => {
    if (!settingsOpen) return;

    previousFocusRef.current = document.activeElement as HTMLElement;

    const timer = setTimeout(() => {
      dialogRef.current?.querySelector<HTMLElement>('button')?.focus();
    }, 50);

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        toggleSettings();
        return;
      }
      if (e.key === 'Tab' && dialogRef.current) {
        const focusable = dialogRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      clearTimeout(timer);
      document.removeEventListener('keydown', handleKeyDown);
      previousFocusRef.current?.focus();
    };
  }, [settingsOpen, toggleSettings]);

  if (!settingsOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={toggleSettings}
      role="presentation"
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        className="bg-[var(--bg-secondary)] rounded-xl border border-[var(--border)] w-full max-w-lg mx-4 max-h-[80vh] flex flex-col animate-fade-in"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <h2 id="settings-title" className="text-base font-semibold text-[var(--text-primary)]">Settings</h2>
          <button
            onClick={toggleSettings}
            aria-label="Close settings"
            className="p-1 rounded-md hover:bg-[var(--bg-hover)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
          >
            <svg aria-hidden="true" width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              <line x1="3" y1="3" x2="11" y2="11" />
              <line x1="11" y1="3" x2="3" y2="11" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* LLM Providers */}
          <section className="glass rounded-xl p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                LLM Providers
              </h3>
              <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-[var(--accent-glow)] text-[var(--accent)]">
                3 active
              </span>
            </div>
            <div className="space-y-2">
              {providers.map((p) => (
                <div
                  key={p.name}
                  className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-[var(--bg-primary)] border border-[var(--border)] hover:border-[var(--border-light)] transition-colors"
                >
                  <div
                    className="w-8 h-8 rounded-lg flex items-center justify-center text-white text-xs font-bold flex-shrink-0"
                    style={{ background: 'var(--gradient-accent)' }}
                  >
                    {p.name[0]}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-[var(--text-primary)] font-medium">{p.name}</p>
                    <p className="text-[11px] text-[var(--text-muted)]">{p.model}</p>
                  </div>
                  {p.primary && (
                    <span className="text-[10px] text-[var(--accent)] font-medium">primary</span>
                  )}
                  <div className="w-2 h-2 rounded-full bg-emerald-500" title="Connected" />
                </div>
              ))}
            </div>
          </section>

          {/* Vector Database */}
          <section className="glass rounded-xl p-5">
            <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-4">
              Vector Database
            </h3>
            <div className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-[var(--bg-primary)] border border-[var(--border)]">
              <div
                className="w-8 h-8 rounded-lg flex items-center justify-center text-white text-xs font-bold flex-shrink-0"
                style={{ background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)' }}
              >
                P
              </div>
              <div className="flex-1">
                <p className="text-sm text-[var(--text-primary)] font-medium">Pinecone</p>
                <p className="text-[11px] text-[var(--text-muted)]">Index: hybrid-rag</p>
              </div>
              <div className="w-2 h-2 rounded-full bg-emerald-500" title="Connected" />
            </div>
          </section>

          {/* Storage */}
          <section className="glass rounded-xl p-5">
            <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-4">
              Storage
            </h3>
            <div className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-[var(--bg-primary)] border border-[var(--border)]">
              <div
                className="w-8 h-8 rounded-lg flex items-center justify-center text-white text-xs font-bold flex-shrink-0"
                style={{ background: 'linear-gradient(135deg, #f59e0b 0%, #ef4444 100%)' }}
              >
                S
              </div>
              <div className="flex-1">
                <p className="text-sm text-[var(--text-primary)] font-medium">Local Storage</p>
                <p className="text-[11px] text-[var(--text-muted)]">data/documents + DuckDB</p>
              </div>
              <div className="w-2 h-2 rounded-full bg-emerald-500" title="Active" />
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
