import { memo, useState, useCallback, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';
import type { ChatResponse } from '../../types/api';
import type { ViewerDoc } from '../../stores/uiStore';
import Badge from '../shared/Badge';
import CitationChipRow from './CitationChipRow';
import RelatedDocsList from './RelatedDocsList';
import DocListResponse from './DocListResponse';
import SqlArtifact from './SqlArtifact';
import EmailTraceResponse from './EmailTraceResponse';
import ProviderTabs from './ProviderTabs';

// Custom markdown components for better presentation
const markdownComponents: Components = {
  table: ({ children, ...props }) => (
    <div className="overflow-x-auto my-3 rounded-lg border border-[var(--border)]">
      <table className="w-full text-xs" {...props}>{children}</table>
    </div>
  ),
  thead: ({ children, ...props }) => (
    <thead className="bg-[var(--bg-primary)]" {...props}>{children}</thead>
  ),
  th: ({ children, ...props }) => (
    <th className="px-3 py-2 text-left text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wider border-b border-[var(--border)]" {...props}>
      {children}
    </th>
  ),
  td: ({ children, ...props }) => (
    <td className="px-3 py-2 text-[var(--text-primary)] border-b border-[var(--border)]/50" {...props}>
      {children}
    </td>
  ),
  tr: ({ children, ...props }) => (
    <tr className="even:bg-[var(--bg-primary)]/30 hover:bg-[var(--bg-hover)] transition-colors" {...props}>
      {children}
    </tr>
  ),
  strong: ({ children, ...props }) => (
    <strong className="text-[var(--accent)] font-semibold" {...props}>{children}</strong>
  ),
};

interface Props {
  response?: ChatResponse;
  text: string;
  onDocClick: (doc: ViewerDoc) => void;
}

function AssistantMessage({ response, text, onDocClick }: Props) {
  const intent = response?.ui_intent ?? 'answer';
  const hasProviders = response?.provider_answers && response.provider_answers.length > 1;
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [text]);

  return (
    <div className="flex justify-start mb-5 gap-4 px-4 animate-fade-in-up group">
      {/* AI Avatar */}
      <div className="flex-shrink-0 w-8 h-8 rounded-full bg-[var(--accent)] flex items-center justify-center mt-1">
        <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
          <path d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>

      <div className="max-w-4xl min-w-0">
        {/* Intent badge + low confidence indicator */}
        <div className="mb-1.5 flex items-center gap-2">
          <Badge label={intent} />
          {response?.routing_confidence != null && response.routing_confidence < 0.6 && (
            <span className="text-[10px] text-[var(--text-muted)] italic">
              Low confidence routing — try rephrasing for better results
            </span>
          )}
          {/* Copy button — visible on hover */}
          <button
            onClick={handleCopy}
            className="ml-auto opacity-0 group-hover:opacity-100 transition-opacity px-2 py-0.5 rounded text-[10px] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
            title="Copy response"
          >
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </div>

        {/* Main content card */}
        <div className="px-6 py-5 rounded-2xl rounded-tl-sm bg-[var(--bg-surface)] text-sm leading-relaxed shadow-sm">
          {/* Multi-provider tabs OR single answer */}
          {hasProviders ? (
            <ProviderTabs
              answers={response!.provider_answers}
              onSourceClick={onDocClick}
            />
          ) : (
            <div className="prose prose-invert prose-sm max-w-none text-[var(--text-primary)]">
              <ReactMarkdown components={markdownComponents}>{text}</ReactMarkdown>
            </div>
          )}

          {/* Intent-specific rendering */}
          {response && (
            <>
              {intent === 'doc_list' && (
                <DocListResponse
                  docs={response.related_docs}
                  onDocClick={onDocClick}
                />
              )}

              {intent === 'email_trace' && (
                <EmailTraceResponse
                  docs={response.related_docs}
                  onDocClick={onDocClick}
                />
              )}

              {/* Show SQL artifact only when NOT multi-provider (tabs handle their own) */}
              {!hasProviders && intent === 'sql_result' && response.sql_artifact && (
                <SqlArtifact artifact={response.sql_artifact} onSourceClick={onDocClick} />
              )}

              <CitationChipRow
                citations={response.citations}
                onChipClick={onDocClick}
              />

              {intent !== 'doc_list' && intent !== 'email_trace' && (
                <RelatedDocsList
                  docs={response.related_docs}
                  onDocClick={onDocClick}
                />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default memo(AssistantMessage);
