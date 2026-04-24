import type { LibraryDocument } from '../types/api';

export interface EmailGroup {
  key: string;
  participants: [string, string];
  emails: LibraryDocument[];
  latestDate: string;
  displayLabel: string;
}

function normalize(s: string): string {
  const raw = (s || '').trim();
  if (!raw) return 'unknown';
  // Strip email address in angle brackets: "Name <x@y.com>" -> "Name"
  const head = raw.split('<')[0].trim();
  return (head || raw).toLowerCase();
}

export function groupEmailsByParticipantPair(docs: LibraryDocument[]): EmailGroup[] {
  const groups = new Map<string, EmailGroup>();

  for (const d of docs) {
    const meta = d.notice_metadata;
    const from = normalize(meta?.sender || '');
    const firstRecipient = (meta?.recipient || '').split(',')[0];
    const to = normalize(firstRecipient);
    const pair = ([from, to].sort() as [string, string]);
    const key = pair.join('||');

    if (!groups.has(key)) {
      groups.set(key, {
        key,
        participants: pair,
        emails: [],
        latestDate: '',
        displayLabel: `${pair[0]} \u2194 ${pair[1]}`,
      });
    }
    groups.get(key)!.emails.push(d);
  }

  for (const g of groups.values()) {
    g.emails.sort((a, b) =>
      (a.notice_metadata?.date || '').localeCompare(b.notice_metadata?.date || ''),
    );
    g.latestDate = g.emails[g.emails.length - 1]?.notice_metadata?.date || '';
  }

  return Array.from(groups.values()).sort((a, b) =>
    b.latestDate.localeCompare(a.latestDate),
  );
}
