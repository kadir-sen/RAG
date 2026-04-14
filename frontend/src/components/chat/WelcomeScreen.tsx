import { useRef, useEffect, useState, type ReactNode } from 'react';
import type { AppMode } from '../../stores/chatStore';
import apiClient from '../../api/client';

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

interface LibrarySummary {
  total_files: number;
  by_file_type: Record<string, number>;
  by_doc_type: Record<string, number>;
  total_tables: number;
}

const DOC_TYPE_LABELS: Record<string, string> = {
  letter: 'Letters', notice: 'Notices', email: 'Emails',
  report: 'Reports', dpr: 'Daily Reports', contract: 'Contracts',
  minutes: 'Minutes', transmittal: 'Transmittals', data_file: 'Data Files',
  unclassified: 'Other',
};

const EXAMPLE_QUERIES: { icon: string; text: string; category: string }[] = [
  { icon: '👷', text: 'How many workers were deployed by trade last month?', category: 'Manpower' },
  { icon: '🏗️', text: 'What is the total crane utilization by block?', category: 'Equipment' },
  { icon: '📊', text: 'What is the overall project progress percentage?', category: 'Progress' },
  { icon: '📄', text: 'What are the key contract terms about delay penalties?', category: 'Documents' },
  { icon: '📋', text: 'List all notices sent by the contractor this year', category: 'Correspondence' },
  { icon: '📈', text: 'Show the monthly manpower trend across all blocks', category: 'Trends' },
];

export default function WelcomeScreen({ onModeSelect, onSend }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [summary, setSummary] = useState<LibrarySummary | null>(null);
  const [summaryError, setSummaryError] = useState(false);

  useEffect(() => {
    apiClient.get<LibrarySummary>('/library/summary')
      .then(({ data }) => setSummary(data))
      .catch(() => setSummaryError(true));
  }, []);

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
    <div className="flex-1 flex flex-col items-center overflow-y-auto p-6 md:p-8 w-full relative">
      {/* Big Logo */}
      <div className="mb-6 md:mb-8 flex flex-col items-center animate-fade-in-up mt-auto">
        <div className="mb-3 md:mb-4" aria-hidden="true">
          <svg className="w-16 h-16 md:w-24 md:h-24 lg:w-[120px] lg:h-[120px]" viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M48.5 25L20 100H35L41.5 82H78.5L85 100H100L71.5 25H48.5ZM47 67L60 31L73 67H47Z" fill="white" />
            <path d="M10 70C30 70 40 45 60 45C80 45 90 70 110 70" stroke="#8B5CF6" strokeWidth="8" strokeLinecap="round" />
            <path d="M95 25H110V100H95V25Z" fill="#8B5CF6" />
          </svg>
        </div>

        <h1 className="text-2xl sm:text-3xl md:text-4xl lg:text-5xl font-semibold tracking-tight text-white mb-6 md:mb-10 text-center">
          Construction Project Intelligence
        </h1>
      </div>

      {/* Search bar */}
      <div className="w-full max-w-3xl relative mb-8 md:mb-12 animate-fade-in-up" style={{ animationDelay: '0.05s' }}>
        <div className="absolute inset-y-0 left-4 flex items-center pointer-events-none" aria-hidden="true">
          <svg className="w-6 h-6 text-[var(--text-secondary)]" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <path d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <label htmlFor="welcome-search" className="sr-only">Search your project</label>
        <input
          id="welcome-search"
          ref={inputRef}
          type="text"
          placeholder="Ask about equipment hours, manpower, progress..."
          onKeyDown={handleKeyDown}
          className="w-full bg-[rgba(255,255,255,0.08)] border border-[rgba(255,255,255,0.2)] rounded-xl py-4 pl-12 pr-16 text-white placeholder-[var(--text-secondary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent transition-all backdrop-blur-sm shadow-inner text-base"
          autoFocus
        />
        <button
          onClick={handleSend}
          aria-label="Send message"
          className="absolute right-2 top-1/2 -translate-y-1/2 w-10 h-10 bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white rounded-lg flex items-center justify-center transition-colors shadow-md"
          style={{ boxShadow: '0 4px 12px rgba(123, 90, 242, 0.3)' }}
        >
          <svg aria-hidden="true" className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
            <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z" />
          </svg>
        </button>
      </div>

      {/* Feature cards */}
      <div
        className="grid grid-cols-1 md:grid-cols-2 gap-4 md:gap-6 w-full max-w-4xl animate-fade-in-up"
        style={{ animationDelay: '0.1s' }}
      >
        {FEATURE_CARDS.map((card) => (
          <button
            key={card.title}
            onClick={() => onModeSelect(card.mode)}
            className="glass-card p-4 md:p-6 text-left group hover:bg-[rgba(255,255,255,0.06)] transition-all duration-300 cursor-pointer"
          >
            <div className="w-9 h-9 md:w-10 md:h-10 rounded-lg border border-[var(--border)] bg-[var(--bg-input)] flex items-center justify-center mb-3 md:mb-4 group-hover:border-[var(--text-secondary)] transition-colors">
              {card.icon}
            </div>
            <h3 className="text-base md:text-lg font-semibold text-white mb-1.5 md:mb-2">
              {card.title}
            </h3>
            <p className="text-xs md:text-sm text-[var(--text-secondary)] leading-relaxed">
              {card.description}
            </p>
          </button>
        ))}
      </div>

      {/* Example queries */}
      <div
        className="w-full max-w-4xl animate-fade-in-up mt-2"
        style={{ animationDelay: '0.12s' }}
      >
        <p className="text-xs text-[var(--text-muted)] mb-3 font-medium uppercase tracking-wider">
          Try asking
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
          {EXAMPLE_QUERIES.map((q) => (
            <button
              key={q.text}
              onClick={() => onSend(q.text)}
              className="text-left px-3 py-2.5 rounded-lg bg-[rgba(255,255,255,0.04)] border border-[rgba(255,255,255,0.08)] hover:bg-[rgba(255,255,255,0.08)] hover:border-[rgba(255,255,255,0.15)] transition-all duration-200 group cursor-pointer"
            >
              <span className="text-sm mr-1.5">{q.icon}</span>
              <span className="text-xs text-[var(--text-secondary)] group-hover:text-white transition-colors leading-relaxed">
                {q.text}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Document classification summary */}
      {summary && summary.total_files > 0 && (
        <div
          className="mt-8 w-full max-w-4xl animate-fade-in-up"
          style={{ animationDelay: '0.15s' }}
        >
          <p className="text-xs text-[var(--text-muted)] mb-2 font-medium uppercase tracking-wider">
            Project Library — {summary.total_files} files, {summary.total_tables} tables
          </p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(summary.by_doc_type).map(([type, count]) => (
              <span
                key={type}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-[rgba(255,255,255,0.06)] border border-[var(--border)] text-xs text-[var(--text-secondary)]"
              >
                <span className="font-semibold text-[var(--text-primary)]">{count}</span>
                {DOC_TYPE_LABELS[type] || type}
              </span>
            ))}
          </div>
        </div>
      )}

      {summaryError && !summary && (
        <p className="text-xs text-[var(--text-muted)] mt-4">Could not load library summary.</p>
      )}

      {/* Footer disclaimer */}
      <div className="mt-auto pt-6 pb-2 w-full text-center shrink-0">
        <p className="text-xs text-[var(--text-secondary)]">
          AI-powered construction analytics. Always verify critical project decisions.
        </p>
      </div>
    </div>
  );
}
