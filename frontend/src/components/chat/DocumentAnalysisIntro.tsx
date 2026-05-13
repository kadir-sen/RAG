import EngineeringInputBar from '../ui/EngineeringInputBar';
import MonoTag from '../ui/MonoTag';
import DocumentAnalysisTimeline, { type TimelineEvent } from './DocumentAnalysisTimeline';
import { getFileTypeBadge } from '../../styles/tokens';

interface Props {
  onSend: (text: string) => void;
}

const SAMPLE_EVENTS: TimelineEvent[] = [
  { date: '2016-02', label: 'Feb 2016', type: 'EML', badge: getFileTypeBadge('email'), title: 'FW_Vingcard Corridor Panel.msg', who: 'Kumarendra → Francois', tag: 'First reference', note: 'Initial RFI for FASTA panel spec' },
  { date: '2016-09', label: 'Sep 2016', type: 'EML', badge: getFileTypeBadge('email'), title: 'Access control card graphics.msg', who: 'Internal · 4 recipients', tag: 'Spec', note: 'Card-graphics revision attached' },
  { date: '2016-10', label: 'Oct 2016', type: 'EML', badge: getFileTypeBadge('email'), title: 'Additional Vingcard items.msg', who: 'Treesa Mondal → all', tag: 'Scope change', note: 'Adds 23 corridor doors + GPIOU module' },
  { date: '2017-01', label: 'Jan 2017', type: 'EML', badge: getFileTypeBadge('email'), title: '170122_FW_Vingcard Corridor RFI.msg', who: 'Paul Thornton → Ozan Altun', tag: 'RFI', note: 'Vendor turnaround request' },
  { date: '2017-05', label: 'May 2017', type: 'EML', badge: getFileTypeBadge('email'), title: 'First Vingcard delivery.msg', who: 'Treesa Mondal', tag: 'Delivery', note: 'First batch arrived on site' },
  { date: '2017-11', label: 'Nov 2017', type: 'PDF', badge: getFileTypeBadge('pdf'), title: 'RLDM5361-R1.pdf', who: 'Contract amendment', tag: 'Contract', note: 'Section 12.4 — penalty clause for FASTA delays', highlight: true },
  { date: '2018-03', label: 'Mar 2018', type: 'XLS', badge: getFileTypeBadge('xls'), title: 'Equipment Log 2.xlsx', who: 'Site · daily log', tag: 'Data · 608 rows', note: 'Crane / hoist hours during FASTA install' },
  { date: '2019-05', label: 'May 2019', type: 'EML', badge: getFileTypeBadge('email'), title: 'RE: Vingcard Corridor Panel.msg', who: 'Francois ↔ Paul ↔ Jurgen', tag: 'Reopen', note: 'Issue raised against installed panels' },
  { date: '2019-08', label: 'Aug 2019', type: 'PDF', badge: getFileTypeBadge('pdf'), title: 'TABH_SIRA approval Letter.pdf', who: 'Authority sign-off', tag: 'Approval', note: 'Final FASTA system approval' },
];

export default function DocumentAnalysisIntro({ onSend }: Props) {
  const submit = (text: string) => {
    onSend(`Show me all documents related to "${text}", chronologically.`);
  };

  return (
    <div className="flex-1 overflow-y-auto welcome-blueprint">
      <div className="max-w-5xl mx-auto px-6 md:px-10 py-8 md:py-10 flex flex-col gap-5 animate-fade-in-up">
        <div className="flex items-center gap-3">
          <MonoTag tone="accent" uppercase>Document Analysis</MonoTag>
          <span className="font-mono text-[11px] text-[var(--text-secondary)] tracking-wide">
            topic → chronological roadmap
          </span>
        </div>
        <div>
          <h1 className="text-2xl md:text-3xl font-semibold tracking-tight text-white">
            Trace a topic across the project, in time order.
          </h1>
          <p className="text-sm text-[var(--text-secondary)] mt-1">
            Enter a subject, vendor, or system. Asistant surfaces every related
            email, contract, and data file along a clickable timeline.
          </p>
        </div>

        <EngineeringInputBar
          placeholder='Topic — e.g. "FASTA", "Vingcard", "delay penalties"…'
          ctaLabel="build timeline"
          ariaLabel="Topic"
          inputId="doc-analysis-topic"
          autoFocus
          onSubmit={submit}
        />

        {/* Sample preview header */}
        <div className="flex items-center gap-2 mt-2">
          <span className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-secondary)]">
            Sample preview
          </span>
          <span className="font-mono text-[11px] text-[var(--text-muted)]">
            · "FASTA" — Feb 2016 → Aug 2019 · 9 documents
          </span>
          <span className="flex-1" />
          <span className="font-mono text-[10px] text-[var(--text-muted)]">
            run a topic to load real results
          </span>
        </div>

        <DocumentAnalysisTimeline
          events={SAMPLE_EVENTS}
          caption='Chronological roadmap — sample · "FASTA"'
        />

        {/* Follow-up actions (preview-disabled) */}
        <div className="flex flex-wrap gap-2 mt-3">
          {[
            ['Summarize topic', 'primary'],
            ['Compare contracts'],
            ['Extract key dates'],
            ['Export as report'],
          ].map(([label, kind]) => (
            <button
              key={label}
              disabled
              className={`text-xs px-3 py-1.5 rounded font-mono tracking-wide transition-colors disabled:opacity-50 ${
                kind === 'primary'
                  ? 'bg-[var(--accent)] text-white'
                  : 'border border-[var(--border)] text-[var(--text-secondary)]'
              }`}
            >
              {kind === 'primary' ? '↳ ' : ''}
              {label}
            </button>
          ))}
          <span className="self-center font-mono text-[10px] text-[var(--text-muted)]">
            available once a topic is loaded
          </span>
        </div>
      </div>
    </div>
  );
}
