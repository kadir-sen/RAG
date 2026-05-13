import { memo, useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';
import type { ChatResponse } from '../../types/api';
import type { ViewerDoc } from '../../stores/uiStore';
import { useChatStore } from '../../stores/chatStore';
import Badge from '../shared/Badge';
import CitationChipRow from './CitationChipRow';
import RelatedDocsList from './RelatedDocsList';
import DocListResponse from './DocListResponse';
import SqlArtifact from './SqlArtifact';
import EmailTraceResponse from './EmailTraceResponse';
import CtaButton from './CtaButton';
import DocumentAnalysisTimeline, { mapRelatedDocsToTimeline } from './DocumentAnalysisTimeline';

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
  timestamp?: number;
  onDocClick: (doc: ViewerDoc) => void;
  failedText?: string;
  onRetry?: (text: string) => void;
}

function formatTime(ts?: number): string {
  if (!ts) return '';
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function AssistantMessage({ response, text, timestamp, onDocClick, failedText, onRetry }: Props) {
  const intent = response?.ui_intent ?? 'answer';
  // Provider names are hidden from the UI; always render the primary text.
  const _unusedProviderAnswers = response?.provider_answers; void _unusedProviderAnswers;
  const activeMode = useChatStore((s) => s.activeMode);
  const showTimeline =
    activeMode === 'document_analysis' &&
    intent === 'doc_list' &&
    !!response?.related_docs?.length;
  const intentLabel = showTimeline ? 'timeline' : intent;
  const time = formatTime(timestamp);
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [text]);

  return (
    <div className="mb-6 px-4 animate-fade-in-up group">
      <div className="max-w-4xl min-w-0">
        {/* Intent label row — mono "CIQ · {kind}" + low confidence + copy */}
        <div className="mb-1.5 flex flex-wrap items-center gap-1.5 md:gap-2">
          <span className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--accent)]">
            Asistant · {intentLabel}{time && ` · ${time}`}
          </span>
          {response?.routing_confidence != null && response.routing_confidence < 0.6 && (
            <Badge label="low confidence" />
          )}
          {/* Copy button — visible on hover */}
          <button
            onClick={handleCopy}
            aria-label={copied ? 'Response copied' : 'Copy response'}
            className="ml-auto opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity px-2 py-0.5 rounded text-[10px] font-mono text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
          >
            {copied ? 'copied!' : 'copy'}
          </button>
        </div>

        {/* Main content card — column layout, hairline border, no avatar */}
        <div className="px-4 py-4 md:px-5 md:py-4 rounded-md border border-[var(--border)] bg-[rgba(255,255,255,0.02)] text-sm leading-relaxed">
          {/* Provider tabs are hidden — always render the single primary answer. */}
          <div className="prose prose-invert prose-sm max-w-none text-[var(--text-primary)]">
            <ReactMarkdown components={markdownComponents}>{text}</ReactMarkdown>
          </div>

          {/* Intent-specific rendering */}
          {response && (
            <>
              {intent === 'doc_list' && !showTimeline && (
                <DocListResponse
                  docs={response.related_docs}
                  onDocClick={onDocClick}
                />
              )}

              {showTimeline && (
                <div className="mt-3">
                  <DocumentAnalysisTimeline
                    events={mapRelatedDocsToTimeline(response.related_docs)}
                    onEventClick={(e) => {
                      if (!e.id) return;
                      onDocClick({ docId: e.id, fileName: e.title });
                    }}
                  />
                </div>
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

              {response.cta && <CtaButton cta={response.cta} />}

              <CitationChipRow
                citations={response.citations}
                onChipClick={onDocClick}
              />

              {intent !== 'doc_list' && intent !== 'email_trace' && !showTimeline && (
                <RelatedDocsList
                  docs={response.related_docs}
                  onDocClick={onDocClick}
                />
              )}
            </>
          )}

          {failedText && onRetry && (
            <button
              onClick={() => onRetry(failedText)}
              className="mt-2 px-3 py-1.5 text-xs bg-[var(--accent)] text-white rounded-lg hover:bg-[var(--accent-hover)] transition-colors"
            >
              Retry
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default memo(AssistantMessage);
