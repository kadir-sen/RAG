import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import type { ProviderAnswer } from '../../types/api';
import type { ViewerDoc } from '../../stores/uiStore';
import SqlArtifact from './SqlArtifact';

const PROVIDER_META: Record<string, { label: string; color: string }> = {
  gemini: { label: 'Gemini', color: '#4285f4' },
  openai: { label: 'OpenAI', color: '#10a37f' },
  claude: { label: 'Claude', color: '#d97706' },
};

interface Props {
  answers: ProviderAnswer[];
  onSourceClick: (doc: ViewerDoc) => void;
}

export default function ProviderTabs({ answers, onSourceClick }: Props) {
  const [active, setActive] = useState(0);

  if (!answers || answers.length === 0) return null;

  const current = answers[active];

  return (
    <div className="mt-3">
      {/* Tab bar */}
      <div className="flex gap-1 mb-3 border-b border-[var(--border)] pb-0">
        {answers.map((a, i) => {
          const meta = PROVIDER_META[a.provider] ?? { label: a.provider, color: '#6366f1' };
          const isActive = i === active;
          return (
            <button
              key={a.provider}
              onClick={() => setActive(i)}
              className={`px-3 py-1.5 text-xs font-medium rounded-t-lg transition-all relative ${
                isActive
                  ? 'text-[var(--text-primary)] bg-[var(--bg-surface)]'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]'
              }`}
            >
              <span className="flex items-center gap-1.5">
                <span
                  className="w-2 h-2 rounded-full flex-shrink-0"
                  style={{ background: meta.color }}
                />
                {meta.label}
                <span className="text-[10px] text-[var(--text-muted)] font-normal">
                  ({a.model})
                </span>
              </span>
              {isActive && (
                <div
                  className="absolute bottom-0 left-0 right-0 h-0.5 rounded-t"
                  style={{ background: meta.color }}
                />
              )}
            </button>
          );
        })}
      </div>

      {/* Active provider content */}
      <div className="animate-fade-in">
        {/* Provider badge */}
        <div className="flex items-center gap-1.5 mb-2">
          <span
            className="w-2 h-2 rounded-full"
            style={{ background: (PROVIDER_META[current.provider] ?? { color: '#6366f1' }).color }}
          />
          <span className="text-[10px] font-medium text-[var(--text-muted)] uppercase tracking-wider">
            {current.provider}
          </span>
        </div>

        {/* Answer text */}
        <div className="prose prose-invert prose-sm max-w-none text-[var(--text-primary)]">
          <ReactMarkdown>{current.text || '_No response_'}</ReactMarkdown>
        </div>

        {/* SQL artifact for this provider */}
        {current.sql_artifact && (
          <SqlArtifact artifact={current.sql_artifact} onSourceClick={onSourceClick} />
        )}
      </div>
    </div>
  );
}
