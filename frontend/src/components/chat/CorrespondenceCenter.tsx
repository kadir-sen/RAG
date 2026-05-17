import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getLibrary } from '../../api/libraryApi';
import { useChatStore } from '../../stores/chatStore';
import { useUIStore } from '../../stores/uiStore';
import type { LibraryDocument } from '../../types/api';
import { groupEmailsByParticipantPair } from '../../utils/emailGrouping';
import MonoTag from '../ui/MonoTag';
import EngineeringInputBar from '../ui/EngineeringInputBar';

interface Props {
  onSend: (text: string) => void;
}

const QUICK_ACTIONS: { label: string; tone: 'primary' | 'dashed'; icon: string; prompt: string }[] = [
  {
    label: 'Summarize selected',
    tone: 'primary',
    icon: '↳',
    prompt: 'Summarize the key points and actions from these emails.',
  },
  {
    label: 'Draft a reply',
    tone: 'dashed',
    icon: '✎',
    prompt: 'Draft a professional reply to the most recent email in this thread.',
  },
  {
    label: 'Find key actions',
    tone: 'dashed',
    icon: '!',
    prompt: 'List all action items, deadlines, and commitments from these emails.',
  },
];

function formatTraceDate(value?: string): string {
  if (!value) return '—';
  // Backend dates may be ISO or "YYYY-MM-DD HH:mm". Keep date part + first 5 chars of time.
  const [datePart, timeRaw] = value.split(/[T\s]/);
  const time = (timeRaw || '').slice(0, 5);
  return time ? `${datePart} ${time}` : datePart;
}

function buildEmailBundle(emails: LibraryDocument[]): string {
  return emails
    .map((d, i) => {
      const m = d.notice_metadata;
      return (
        `--- Email ${i + 1} ---\n` +
        `Subject: ${m?.subject || d.file_name}\n` +
        `From: ${m?.sender || 'Unknown'}\n` +
        `To: ${m?.recipient || 'Unknown'}\n` +
        `Date: ${m?.date || 'Unknown'}\n\n` +
        (m?.summary || '').slice(0, 2000)
      );
    })
    .join('\n\n');
}

export default function CorrespondenceCenter({ onSend }: Props) {
  const { selectedEmailIds } = useChatStore();
  const { openDocument } = useUIStore();
  const libraryQuery = useQuery({
    queryKey: ['library'],
    queryFn: getLibrary,
    staleTime: 60_000,
  });

  const { selectedThread, selectedEmails } = useMemo(() => {
    const docs = (libraryQuery.data ?? []).filter(
      (d) => d.file_type === 'email' || d.extension === '.eml' || d.extension === '.msg',
    );
    const groups = groupEmailsByParticipantPair(docs);
    const selectedDocIdSet = new Set(selectedEmailIds);
    const emails = docs
      .filter((d) => selectedDocIdSet.has(d.doc_id))
      .sort((a, b) =>
        (a.notice_metadata?.date || '').localeCompare(b.notice_metadata?.date || ''),
      );
    // The thread the user is acting on = the group containing the most selected emails.
    const counts = new Map<string, number>();
    for (const g of groups) {
      const c = g.emails.filter((e) => selectedDocIdSet.has(e.doc_id)).length;
      if (c > 0) counts.set(g.key, c);
    }
    let bestKey: string | undefined;
    let bestCount = 0;
    for (const [k, v] of counts) {
      if (v > bestCount) {
        bestCount = v;
        bestKey = k;
      }
    }
    const thread = bestKey ? groups.find((g) => g.key === bestKey) : undefined;
    return { selectedThread: thread, selectedEmails: emails };
  }, [libraryQuery.data, selectedEmailIds]);

  const handleQuickAction = (prompt: string) => {
    if (selectedEmails.length === 0) return;
    const bundle = buildEmailBundle(selectedEmails);
    onSend(`${prompt}\n\nSelected emails (${selectedEmails.length}):\n\n${bundle}`);
  };

  const handleAsk = (text: string) => {
    if (selectedEmails.length > 0) {
      const bundle = buildEmailBundle(selectedEmails);
      onSend(
        `${text}\n\nContext — selected emails (${selectedEmails.length}):\n\n${bundle}`,
      );
    } else {
      onSend(text);
    }
  };

  const dateRange = (() => {
    if (selectedEmails.length === 0) return '';
    const first = selectedEmails[0]?.notice_metadata?.date?.split(/[T\s]/)[0];
    const last = selectedEmails.at(-1)?.notice_metadata?.date?.split(/[T\s]/)[0];
    if (!first) return '';
    return last && last !== first ? `${first} → ${last}` : first;
  })();

  const subject = selectedEmails.at(-1)?.notice_metadata?.subject || '';

  return (
    <div className="flex-1 flex flex-col min-h-0 welcome-blueprint">
      <div className="flex-1 overflow-y-auto px-6 md:px-10 py-6 md:py-8">
        <div className="max-w-4xl mx-auto flex flex-col gap-5 animate-fade-in-up">
          {/* Selected thread heading */}
          <div>
            <p className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-secondary)]">
              Selected thread
            </p>
            <h2 className="text-xl md:text-2xl font-semibold text-white tracking-tight mt-1">
              {selectedThread ? selectedThread.displayLabel : 'No thread selected yet'}
            </h2>
            <p className="font-mono text-[11px] text-[var(--text-muted)] mt-1">
              {selectedEmails.length > 0
                ? `${selectedEmails.length} message${selectedEmails.length > 1 ? 's' : ''}${dateRange ? ` · ${dateRange}` : ''}${subject ? ` · ${subject}` : ''}`
                : 'Pick a thread on the left, then choose which emails to include.'}
            </p>
          </div>

          {/* Email trace timeline */}
          <div className="rounded-md border border-[var(--border)] bg-[rgba(255,255,255,0.02)] overflow-hidden">
            <div className="flex items-center justify-between px-4 py-2 border-b border-dashed border-[var(--border)]">
              <span className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-secondary)]">
                Email trace
              </span>
              <span className="font-mono text-[10px] text-[var(--text-muted)]">
                {selectedEmails.length > 0 ? `${selectedEmails.length} scoped` : 'no selection'}
              </span>
            </div>

            {selectedEmails.length === 0 ? (
              <div className="px-6 py-10 text-center">
                <p className="font-mono text-[11px] text-[var(--text-muted)]">
                  ← Select a thread (and check at least one email) to see the trace.
                </p>
              </div>
            ) : (
              <ol className="px-4 md:px-6 py-4 flex flex-col gap-0">
                {selectedEmails.map((email, i) => {
                  const meta = email.notice_metadata;
                  const isLast = i === selectedEmails.length - 1;
                  const summary = (meta?.summary || '').trim();
                  return (
                    <li
                      key={email.doc_id}
                      className={`grid grid-cols-[120px_16px_1fr_auto] items-start gap-3 py-2 ${isLast ? '' : 'border-b border-dashed border-[var(--border)]/60'}`}
                    >
                      <span className="font-mono text-[10px] text-[var(--text-secondary)] pt-1">
                        {formatTraceDate(meta?.date)}
                      </span>
                      <div className="relative flex justify-center pt-1">
                        {!isLast && (
                          <span
                            aria-hidden="true"
                            className="absolute top-3 bottom-[-12px] w-px bg-[var(--accent)] opacity-70"
                          />
                        )}
                        <span
                          aria-hidden="true"
                          className="relative z-[1] w-2 h-2 rounded-full mt-1.5"
                          style={{ background: 'var(--accent)' }}
                        />
                      </div>
                      <div className="min-w-0">
                        <p className="text-[12px] md:text-sm text-white font-medium truncate">
                          {meta?.sender || 'Unknown'} → {meta?.recipient?.split(',')[0] || 'Unknown'}
                        </p>
                        <p className="text-[11px] text-[var(--text-secondary)] truncate">
                          {meta?.subject || email.file_name}
                        </p>
                        {summary && (
                          <p className="text-[11px] text-[var(--text-muted)] mt-0.5 line-clamp-2">
                            {summary}
                          </p>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={() =>
                          openDocument({ docId: email.doc_id, fileName: email.file_name })
                        }
                        className="font-mono text-[10px] text-[var(--accent)] hover:text-[var(--accent-hover)] pt-1 whitespace-nowrap"
                      >
                        view →
                      </button>
                    </li>
                  );
                })}
              </ol>
            )}
          </div>

          {/* Quick prompts */}
          <div className="flex flex-wrap gap-2">
            {QUICK_ACTIONS.map((a) => {
              const disabled = selectedEmails.length === 0;
              return (
                <button
                  key={a.label}
                  type="button"
                  disabled={disabled}
                  onClick={() => handleQuickAction(a.prompt)}
                  className={`text-xs font-mono tracking-wide px-3 py-1.5 rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                    a.tone === 'primary'
                      ? 'bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white'
                      : 'border border-[var(--border)] hover:border-[var(--accent)] text-[var(--text-secondary)] hover:text-white'
                  }`}
                >
                  <span className="mr-1">{a.icon}</span>
                  {a.label}
                  {selectedEmails.length > 0 && a.tone === 'primary' && (
                    <span className="ml-1 opacity-80">({selectedEmails.length})</span>
                  )}
                </button>
              );
            })}
            <span className="self-center font-mono text-[10px] text-[var(--text-muted)]">
              {selectedEmails.length > 0 ? (
                <MonoTag tone="accent">{selectedEmails.length} emails scoped</MonoTag>
              ) : (
                'available once a thread is selected'
              )}
            </span>
          </div>
        </div>
      </div>

      {/* Inline composer pinned at bottom */}
      <div className="px-6 md:px-10 pb-5 pt-3 border-t border-[var(--border)] bg-[var(--bg-primary)]/60">
        <div className="max-w-4xl mx-auto">
          <EngineeringInputBar
            placeholder="Ask about this thread, or pick a quick prompt…"
            ariaLabel="Ask about correspondence"
            inputId="correspondence-ask"
            onSubmit={handleAsk}
          />
        </div>
      </div>
    </div>
  );
}
