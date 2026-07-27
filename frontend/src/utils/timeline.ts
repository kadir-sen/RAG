import { getFileTypeBadge, type FileTypeBadge } from '../styles/tokens';

export interface TimelineEvent {
  id?: string;
  date: string;
  label: string;
  type: string;
  badge: FileTypeBadge;
  title: string;
  who?: string;
  tag?: string;
  note?: string;
  highlight?: boolean;
  /** Source document, shown at the end of the row. Only the chronology area
      sets it — mapRelatedDocsToTimeline leaves it undefined, because there the
      row's title already is the document. */
  source?: string;
}

const MONTH_LABELS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function formatTimelineLabel(date?: string): string {
  if (!date) return '—';
  const datePart = date.split(/[T\s]/)[0];
  const [y, m] = datePart.split('-');
  if (!y) return datePart;
  if (!m) return y;
  const idx = Math.max(0, Math.min(11, Number(m) - 1));
  return `${MONTH_LABELS[idx]} ${y}`;
}

interface RelatedDocLike {
  doc_id: string;
  doc_name: string;
  date: string;
  doc_type: string;
  reason: string;
  sender: string;
  recipient: string;
}

const HIGHLIGHT_DOC_TYPES = new Set(['contract', 'amendment', 'approval', 'notice']);

export function mapRelatedDocsToTimeline(docs: RelatedDocLike[]): TimelineEvent[] {
  return docs
    .filter((d) => d?.doc_id || d?.doc_name)
    .slice()
    .sort((a, b) => (a.date || '9999').localeCompare(b.date || '9999'))
    .map((d) => {
      const ext = d.doc_name.toLowerCase().match(/\.([a-z0-9]+)$/)?.[1];
      const badge = getFileTypeBadge(ext ?? d.doc_type);
      const who =
        d.sender || d.recipient
          ? `${d.sender || 'Unknown'}${d.recipient ? ` → ${d.recipient.split(',')[0]}` : ''}`
          : '';
      return {
        id: d.doc_id,
        date: d.date,
        label: formatTimelineLabel(d.date),
        type: badge.label,
        badge,
        title: d.doc_name,
        who,
        tag: d.doc_type ? d.doc_type.replace(/_/g, ' ') : undefined,
        note: d.reason || undefined,
        highlight: HIGHLIGHT_DOC_TYPES.has((d.doc_type || '').toLowerCase()),
      } satisfies TimelineEvent;
    });
}
