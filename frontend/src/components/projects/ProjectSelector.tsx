import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useProjectStore } from '../../stores/projectStore';

export default function ProjectSelector() {
  const navigate = useNavigate();
  const projects = useProjectStore((s) => s.projects);
  const selected = useProjectStore((s) => s.selectedProjectId);
  const select = useProjectStore((s) => s.select);
  const load = useProjectStore((s) => s.load);
  useEffect(() => { if (!projects.length) void load(); }, [load, projects.length]);
  return (
    <select
      aria-label="Active project"
      value={selected ?? ''}
      onChange={(event) => {
        const value = event.target.value;
        if (value === '__manage__') { navigate('/projects'); return; }
        select(value || null);
        navigate('/');
      }}
      className="max-w-[220px] bg-[var(--bg-primary)] border border-[var(--border)] rounded-[2px] px-2 py-1 font-mono text-[10px] text-[var(--text-secondary)]"
    >
      <option value="">Select project</option>
      {projects.map((project) => <option key={project.project_id} value={project.project_id}>{project.name}</option>)}
      <option value="__manage__">Manage projects…</option>
    </select>
  );
}
