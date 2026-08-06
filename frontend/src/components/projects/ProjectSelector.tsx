import { useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useProjectStore } from '../../stores/projectStore';

export default function ProjectSelector() {
  const navigate = useNavigate();
  const location = useLocation();
  const projects = useProjectStore((s) => s.projects);
  const selected = useProjectStore((s) => s.selectedProjectId);
  const select = useProjectStore((s) => s.select);
  const load = useProjectStore((s) => s.load);
  useEffect(() => { if (!projects.length) void load(); }, [load, projects.length]);

  const current = projects.find((project) => project.project_id === selected) ?? null;

  return (
    <div
      data-testid="project-context"
      className="flex h-11 min-w-0 max-w-full flex-1 items-stretch border border-[var(--border)] bg-[var(--bg-primary)] rounded-[2px] md:flex-none"
    >
      <button
        type="button"
        onClick={() => navigate('/projects')}
        aria-label={current ? `Manage project ${current.name}` : 'Open project management'}
        title="Open project management"
        className="flex min-w-0 flex-1 items-center gap-2 px-2 text-left hover:bg-[var(--bg-hover)] transition-colors md:flex-none md:px-2.5"
      >
        <svg aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 text-[var(--text-secondary)]">
          <path d="M3 6.75A1.75 1.75 0 014.75 5h4l2 2h8.5A1.75 1.75 0 0121 8.75v8.5A1.75 1.75 0 0119.25 19H4.75A1.75 1.75 0 013 17.25z" />
        </svg>
        <span className="min-w-0 leading-tight">
          <span className="hidden sm:block font-mono text-[8px] uppercase tracking-[.16em] text-[var(--text-muted)]">
            {location.pathname === '/projects' ? 'Project management' : 'Active project'}
          </span>
          <span className="block max-w-[calc(100vw-126px)] truncate text-[11px] font-semibold text-[var(--text-primary)] md:max-w-[210px]">
            {current?.name ?? 'Select a project'}
          </span>
        </span>
      </button>
      <div className="relative w-11 shrink-0 border-l border-[var(--border)] hover:bg-[var(--bg-hover)] transition-colors">
        <select
          aria-label="Switch active project"
          value={selected ?? ''}
          onChange={(event) => {
            const value = event.target.value;
            select(value || null);
            // A project switch is a workspace boundary. Return module pages to
            // the main menu so local chronology/report state from the previous
            // record cannot remain on screen. Management stays open while the
            // user organises several projects in sequence.
            if (!value) navigate('/projects');
            else if (location.pathname !== '/projects' && location.pathname !== '/') navigate('/');
          }}
          className="absolute inset-0 z-10 h-full w-full cursor-pointer opacity-0"
        >
          <option value="">Select project</option>
          {projects.map((project) => <option key={project.project_id} value={project.project_id}>{project.name}</option>)}
        </select>
        <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-[var(--text-secondary)]">
          <path d="m7 10 5 5 5-5" />
        </svg>
      </div>
    </div>
  );
}
