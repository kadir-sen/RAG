import { useRef, type ReactNode } from 'react';
import type { AppMode } from '../../stores/chatStore';

interface Props {
  onModeSelect: (mode: AppMode) => void;
  onSend: (text: string) => void;
}

const FEATURE_CARDS: { icon: ReactNode; title: string; description: string; mode: AppMode }[] = [
  {
    icon: (
      <svg className="w-5 h-5 text-[var(--text-secondary)] group-hover:text-white transition-colors" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
        <path d="M21.75 6.75v10.5a2.25 2.25 0 01-2.25 2.25h-15a2.25 2.25 0 01-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25m19.5 0v.243a2.25 2.25 0 01-1.07 1.916l-7.5 4.615a2.25 2.25 0 01-2.36 0L3.32 8.91a2.25 2.25 0 01-1.07-1.916V6.75" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    title: 'Correspondence Mode',
    description: 'Draft emails, track notices, and manage project communications.',
    mode: 'correspondence',
  },
  {
    icon: (
      <svg className="w-5 h-5 text-[var(--text-secondary)] group-hover:text-white transition-colors" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
        <path d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    title: 'Document Analysis',
    description: 'Extract insights from contracts, specifications, and reports.',
    mode: 'document_analysis',
  },
];

export default function WelcomeScreen({ onModeSelect, onSend }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSend = () => {
    const value = inputRef.current?.value.trim();
    if (!value) return;
    onSend(value);
    if (inputRef.current) inputRef.current.value = '';
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 w-full relative">
      {/* Big Logo */}
      <div className="mb-8 flex flex-col items-center animate-fade-in-up">
        <div className="mb-4">
          <svg width="120" height="120" viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M48.5 25L20 100H35L41.5 82H78.5L85 100H100L71.5 25H48.5ZM47 67L60 31L73 67H47Z" fill="white" />
            <path d="M10 70C30 70 40 45 60 45C80 45 90 70 110 70" stroke="#8B5CF6" strokeWidth="8" strokeLinecap="round" />
            <path d="M95 25H110V100H95V25Z" fill="#8B5CF6" />
          </svg>
        </div>

        <h1 className="text-5xl font-semibold tracking-tight text-white mb-10">
          Construction Project Intelligence
        </h1>
      </div>

      {/* Search bar */}
      <div className="w-full max-w-3xl relative mb-12 animate-fade-in-up" style={{ animationDelay: '0.05s' }}>
        <div className="absolute inset-y-0 left-4 flex items-center pointer-events-none">
          <svg className="w-6 h-6 text-[var(--text-secondary)]" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <path d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <input
          ref={inputRef}
          type="text"
          placeholder="Ask about equipment hours, manpower, progress..."
          onKeyDown={handleKeyDown}
          className="w-full bg-[rgba(255,255,255,0.08)] border border-[rgba(255,255,255,0.2)] rounded-xl py-4 pl-12 pr-16 text-white placeholder-[var(--text-secondary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent transition-all backdrop-blur-sm shadow-inner text-base"
          autoFocus
        />
        <button
          onClick={handleSend}
          className="absolute inset-y-2 right-2 bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white p-2 rounded-lg flex items-center justify-center transition-colors shadow-md"
          style={{ boxShadow: '0 4px 12px rgba(123, 90, 242, 0.3)' }}
        >
          <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
            <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z" />
          </svg>
        </button>
      </div>

      {/* Feature cards */}
      <div
        className="grid grid-cols-1 md:grid-cols-2 gap-6 w-full max-w-4xl animate-fade-in-up"
        style={{ animationDelay: '0.1s' }}
      >
        {FEATURE_CARDS.map((card) => (
          <button
            key={card.title}
            onClick={() => onModeSelect(card.mode)}
            className="glass-card p-6 text-left group hover:bg-[rgba(255,255,255,0.06)] transition-all duration-300 cursor-pointer"
          >
            <div className="w-10 h-10 rounded-lg border border-[var(--border)] bg-[var(--bg-input)] flex items-center justify-center mb-4 group-hover:border-[var(--text-secondary)] transition-colors">
              {card.icon}
            </div>
            <h3 className="text-lg font-semibold text-white mb-2">
              {card.title}
            </h3>
            <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
              {card.description}
            </p>
          </button>
        ))}
      </div>

      {/* Footer disclaimer */}
      <div className="absolute bottom-6 w-full text-center pointer-events-none">
        <p className="text-xs text-[var(--text-secondary)]">
          AI-powered construction analytics. Always verify critical project decisions.
        </p>
      </div>
    </div>
  );
}
