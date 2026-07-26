import { memo, useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';
import type { ChatResponse, ActivityStep } from '../../types/api';
import type { ViewerDoc } from '../../stores/uiStore';
import Badge from '../shared/Badge';
import Avatar from './Avatar';
import InlineCitations from './InlineCitations';
import RelatedDocsList from './RelatedDocsList';
import DocListResponse from './DocListResponse';
import SqlArtifact from './SqlArtifact';
import EmailTraceResponse from './EmailTraceResponse';
import CtaButton from './CtaButton';
import DocumentAnalysisTable from './DocumentAnalysisTable';
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
  activities?: ActivityStep[];
}

// Collapsed trail of the activity steps the assistant took to produce the answer.
function StepTrail({ steps }: { steps: ActivityStep[] }) {
  if (!steps.length) return null;
  return (
    <details className="mb-2 group/steps">
      {/* Mono tag in the sheet's label convention (MODE.01, ACCESS · 01), and
          the same numbered revision column the live ActivityFeed draws — the
          trail is that feed, settled. */}
      <summary className="cursor-pointer list-none inline-block px-1.5 py-0.5 border border-[var(--border)] rounded-[2px] text-[10px] font-mono uppercase tracking-[0.18em] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:border-[var(--border-light)] select-none transition-colors">
        steps · {steps.length}
      </summary>
      <ol className="mt-1.5 flex flex-col border-l border-[var(--border)]">
        {steps.map((s, i) => (
          <li
            key={s.seq}
            className="flex items-baseline gap-2.5 pl-3 py-[2px] text-[11px] text-[var(--text-muted)]"
          >
            <span className="font-mono text-[10px] tabular-nums w-4 shrink-0" aria-hidden="true">
              {String(i + 1).padStart(2, '0')}
            </span>
            <span className="font-mono w-3 shrink-0 text-center text-[var(--accent)]" aria-hidden="true">✓</span>
            <span className="truncate">{s.label}</span>
            {s.detail && <span className="font-mono text-[10px] opacity-70 truncate">{s.detail}</span>}
          </li>
        ))}
      </ol>
    </details>
  );
}

function formatTime(ts?: number): string {
  if (!ts) return '';
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function AssistantMessage({ response, text, timestamp, onDocClick, failedText, onRetry, activities }: Props) {
  const intent = response?.ui_intent ?? 'answer';
  // Mode-less: whenever the router returns a document list (FILE_LIST / TIMELINE
  // → ui_intent "doc_list") with related documents, render them as a single
  // clickable, chronological table on the home page — the rich "document
  // analysis" output without needing a dedicated mode. Replaces the flat
  // doc-list table / timeline / chip strip so we never stack two views.
  const relatedCount = response?.related_docs?.length ?? 0;
  // Chronological LIST query (TIMELINE) → vertical timeline. FILE_LIST → table.
  const showTimeline = intent === 'timeline' && relatedCount > 0;
  const showDocAnalysisTable = intent === 'doc_list' && relatedCount > 0;
  // Related documents attached to a normal answer (document/hybrid/…): render as
  // the rich chronological table (≥2 docs) instead of the flat bubble strip, so
  // every "related documents" surface is the structured table the user expects.
  const showRelatedAsTable =
    intent !== 'doc_list' && intent !== 'timeline' &&
    intent !== 'email_trace' && intent !== 'sql_result' && relatedCount >= 2;
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
      <div className="max-w-5xl min-w-0 flex items-start gap-3">
        <Avatar variant="assistant" />
        <div className="min-w-0 flex-1">
          {/* Hover-only metadata strip */}
          {(response?.route === 'AGENT' ||
            (response?.routing_confidence != null && response.routing_confidence < 0.6)) && (
            <div className="mb-1.5 flex items-center gap-2">
              {response?.route === 'AGENT' && <Badge label="agent" />}
              {response?.routing_confidence != null && response.routing_confidence < 0.6 && (
                <Badge label="low confidence" />
              )}
            </div>
          )}

          {/* Main content card — dark surface, soft border, larger radius */}
          <div className="px-4 py-4 md:px-5 md:py-4 assistant-card text-sm leading-relaxed">
            {!!activities?.length && <StepTrail steps={activities} />}
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
                {showTimeline ? (
                  <div className="mt-3">
                    <DocumentAnalysisTimeline
                      events={mapRelatedDocsToTimeline(response.related_docs)}
                      onEventClick={(e) => {
                        if (!e.id) return;
                        onDocClick({ docId: e.id, fileName: e.title });
                      }}
                    />
                  </div>
                ) : showDocAnalysisTable || showRelatedAsTable ? (
                  <div className="mt-3">
                    <DocumentAnalysisTable
                      events={mapRelatedDocsToTimeline(response.related_docs)}
                      onEventClick={(e) => {
                        if (!e.id) return;
                        onDocClick({ docId: e.id, fileName: e.title });
                      }}
                    />
                  </div>
                ) : (
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

                    {/* SQL artifact (provider tabs are hidden — always render). */}
                    {intent === 'sql_result' && response.sql_artifact && (
                      <SqlArtifact artifact={response.sql_artifact} onSourceClick={onDocClick} />
                    )}

                    {/* A single related doc → compact bubble strip (table is overkill). */}
                    {intent !== 'doc_list' && intent !== 'timeline' &&
                     intent !== 'email_trace' && (
                      <RelatedDocsList
                        docs={response.related_docs}
                        onDocClick={onDocClick}
                      />
                    )}
                  </>
                )}

                {response.cta && <CtaButton cta={response.cta} />}
              </>
            )}

            {failedText && onRetry && (
              <button
                onClick={() => onRetry(failedText)}
                className="mt-2 px-3 py-1.5 text-xs bg-[var(--accent)] text-[var(--accent-ink)] rounded-lg hover:bg-[var(--accent-hover)] transition-colors"
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
