import { useEffect, useState } from 'react';
import apiClient from '../../api/client';

interface Props {
  onSend?: (text: string) => void;
}

// Starter queries — click to run. Chronology lives in its own area now, so
// these stay on what the chat is for: reading documents, correspondence, data.
const SUGGESTIONS: { label: string; prompt: string; symbol: string }[] = [
  { symbol: '▤', label: 'Find documents on a topic', prompt: 'Which documents discuss "the topic"?' },
  { symbol: '✉', label: 'Summarize recent correspondence', prompt: 'Summarize the latest correspondence and list any unanswered items.' },
  { symbol: '◷', label: 'What a notice says', prompt: 'What does the latest delay notice say, and who sent it?' },
  { symbol: '∑', label: 'Ask a project data question', prompt: 'How many workers were on site last month?' },
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

const LIBRARY_KPI_LABELS: Record<string, string> = {
  letter: 'letters',
  notice: 'notices',
  email: 'emails',
  report: 'reports',
  dpr: 'daily reports',
  contract: 'contracts',
  minutes: 'minutes',
  transmittal: 'transmittals',
  data_file: 'data files',
  unclassified: 'other',
};

export default function WelcomeScreen({ onSend }: Props) {
  const [summary, setSummary] = useState<LibrarySummary | null>(null);
  const [summaryError, setSummaryError] = useState(false);

  useEffect(() => {
    apiClient.get<LibrarySummary>('/library/summary')
      .then(({ data }) => setSummary(data))
      .catch(() => setSummaryError(true));
  }, []);

  // Top KPI tiles — pulled from real /library/summary, filled with sensible fallbacks
  const totalFiles = summary?.total_files ?? 0;
  const totalTables = summary?.total_tables ?? 0;
  const docCounts = summary?.by_doc_type ?? {};
  const dataFiles = (docCounts.data_file ?? 0);
  const emails = (docCounts.email ?? 0);
  const letters = (docCounts.letter ?? 0) + (docCounts.notice ?? 0);
  const reports = (docCounts.report ?? 0) + (docCounts.dpr ?? 0);
  const otherCount = totalFiles - dataFiles - emails - letters - reports;

  const kpis = [
    [String(totalFiles), 'files'],
    [String(totalTables), 'tables'],
    [String(dataFiles), 'data'],
    [String(emails), 'emails'],
    [String(letters), 'letters'],
    [String(otherCount > 0 ? otherCount : reports), otherCount > 0 ? 'other' : 'reports'],
  ] as const;

  return (
    <div className="flex-1 overflow-y-auto w-full relative welcome-blueprint">
      <div className="max-w-6xl mx-auto px-5 sm:px-8 md:px-10 lg:px-14 py-8 md:py-10 flex flex-col gap-7 animate-fade-in-up">
        {/* Engineering mark */}
        <div className="flex items-center gap-4">
          <div
            className="w-14 h-14 grid place-items-center border border-[var(--border)] bg-[var(--wash)] rounded"
            aria-hidden="true"
          >
            <span className="font-mono font-bold text-[var(--text-primary)] tracking-wider text-lg">CO</span>
          </div>
          <div>
            <h1 className="text-2xl md:text-3xl font-semibold tracking-tight text-[var(--text-primary)]">
              <span>CO</span>
              <span className="text-[var(--brand)]">Air</span>
            </h1>
            <p className="text-xs md:text-sm text-[var(--text-secondary)] font-mono mt-1 tracking-wide">
              chat · cite · verify — your project data, on demand
            </p>
          </div>
        </div>

        {/* Starter suggestions — click to run a query (router picks the skill) */}
        <div>
          <p className="font-mono text-[10px] text-[var(--text-secondary)] tracking-[0.18em] uppercase mb-3">Try</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 lg:gap-4">
            {SUGGESTIONS.map((s) => (
              <button
                key={s.label}
                onClick={() => onSend?.(s.prompt)}
                className="group flex items-center gap-3 bg-[var(--wash)] border border-[var(--border)] hover:border-[var(--accent)] hover:bg-[var(--wash-firm)] rounded-md px-4 py-3.5 text-left transition-colors"
              >
                <span className="font-mono text-lg text-[var(--text-primary)] w-6 text-center">{s.symbol}</span>
                <span className="text-[13px] md:text-sm text-[var(--text-secondary)] group-hover:text-[var(--text-primary)] flex-1">{s.label}</span>
                <span className="font-mono text-[11px] text-[var(--accent)] opacity-0 group-hover:opacity-100 transition-opacity">run →</span>
              </button>
            ))}
          </div>
        </div>

        {/* Project library — KPI grid */}
        {summary && summary.total_files > 0 && (
          <section aria-labelledby="library-title">
            <p id="library-title" className="font-mono text-[10px] text-[var(--text-secondary)] tracking-[0.18em] uppercase">
              Project library
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mt-3">
              {kpis.map(([n, l]) => (
                <div
                  key={l}
                  className="px-3 py-3 rounded bg-[var(--wash)] border border-[var(--border)]"
                >
                  <div className="font-mono text-2xl text-[var(--text-primary)] tabular-nums leading-none">{n}</div>
                  <div className="font-mono text-[10px] text-[var(--text-secondary)] tracking-[0.12em] uppercase mt-1.5">
                    {l}
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {Object.entries(summary.by_doc_type).map(([type, count]) => (
                <span
                  key={type}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded font-mono text-[11px] bg-[var(--wash)] border border-[var(--border)] text-[var(--text-secondary)]"
                >
                  <span className="text-[var(--text-primary)]">{count}</span>
                  <span className="lowercase">{LIBRARY_KPI_LABELS[type] || DOC_TYPE_LABELS[type] || type}</span>
                </span>
              ))}
            </div>
          </section>
        )}

        {summaryError && !summary && (
          <p className="text-xs text-[var(--text-muted)] font-mono">⚠ could not load library summary.</p>
        )}

        <p className="font-mono text-[11px] text-[var(--text-muted)] text-center pt-4">
          AI-powered analytics. Verify critical decisions.
        </p>
      </div>
    </div>
  );
}
