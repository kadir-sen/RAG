import { memo, useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';
import type { ChatResponse } from '../../types/api';
import type { ViewerDoc } from '../../stores/uiStore';
import { useChatStore } from '../../stores/chatStore';
import Badge from '../shared/Badge';
import Avatar from './Avatar';
import InlineCitations from './InlineCitations';
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
    <strong className="text-[var(--text-primary)] font-semibold" {...props}>{children}</strong>
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
  const activeMode = useChatStore((s) => s.activeMode);
  const showTimeline =
    activeMode === 'document_analysis' &&
    intent === 'doc_list' &&
    !!response?.related_docs?.length;
  const time = formatTime(timestamp);
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [text]);

  // Inline citations are only meaningful for plain answer responses where the
  // text itself is the primary content. Doc-list / timeline / email-trace /
  // sql_result intents render their own structured sources.
  const showInlineCitations =
    intent === 'answer' && !!response?.citations?.length;

  return (
    <div className="mb-6 px-4 animate-fade-in-up group">
      <div className="max-w-4xl min-w-0 flex items-start gap-3">
        <Avatar variant="assistant" />
        <div className="min-w-0 flex-1">
          {/* Hover-only metadata strip */}
          {response?.routing_confidence != null && response.routing_confidence < 0.6 && (
            <div className="mb-1.5 flex items-center gap-2">
              <Badge label="low confidence" />
            </div>
          )}

          {/* Main content card — dark surface, soft border, larger radius */}
          <div className="px-4 py-4 md:px-5 md:py-4 assistant-card text-sm leading-relaxed">
            <div className="prose prose-invert prose-sm max-w-none text-[var(--text-primary)]">
              <ReactMarkdown components={markdownComponents}>{text}</ReactMarkdown>
              {showInlineCitations && (
                <p className="!mt-2 !mb-0">
                  <InlineCitations
                    citations={response?.citations}
                    onChipClick={onDocClick}
                  />
                </p>
              )}
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

                {/* SQL artifact (provider tabs are hidden — always render). */}
                {intent === 'sql_result' && response.sql_artifact && (
                  <SqlArtifact artifact={response.sql_artifact} onSourceClick={onDocClick} />
                )}

                {response.cta && <CtaButton cta={response.cta} />}

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

          {/* Footer: timestamp + copy (hover-only) */}
          <div className="mt-1 flex items-center gap-2 text-[10px] font-mono text-[var(--text-muted)] opacity-0 group-hover:opacity-100 transition-opacity">
            {time && <span>{time}</span>}
            <button
              onClick={handleCopy}
              aria-label={copied ? 'Response copied' : 'Copy response'}
              className="ml-auto px-2 py-0.5 rounded hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors"
            >
              {copied ? 'copied!' : 'copy'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default memo(AssistantMessage);
