import AIReportPanel from '../components/reports/AIReportPanel';
import { TOOLKIT_URL } from '../config/modules';

export default function ForensicPage() {
  return (
    <div className="flex-1 min-w-0 overflow-y-auto">
      <AIReportPanel module="forensic" />
      <div className="max-w-4xl mx-auto px-4 md:px-8 py-8">
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">Forensic Reports</h1>
        <p className="mt-2 text-[13px] leading-6 text-[var(--text-secondary)]">Generate a project-grounded draft above. Findings carry supporting evidence, counter-evidence, confidence and missing-record fields. “Issue” uses the strict verification gate.</p>
        <div className="mt-6 border border-[var(--border)] bg-[var(--wash)] rounded-[3px] p-5">
          <p className="font-mono text-[10px] uppercase tracking-[.16em] text-[var(--text-muted)]">Delay Analysis Toolkit</p>
          <p className="mt-2 text-[12px] text-[var(--text-secondary)]">Use the existing toolkit for programme calculations, DCMA checks and critical-path evidence. The report model does not invent these calculations.</p>
          <a href={TOOLKIT_URL} target="_blank" rel="noreferrer" className="inline-block mt-4 px-3 py-2 border border-[var(--border)] text-[11px] text-[var(--text-primary)]">Open toolkit ↗</a>
        </div>
      </div>
    </div>
  );
}
